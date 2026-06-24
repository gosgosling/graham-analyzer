"""Создание логического бэкапа PostgreSQL через scripts/pg_backup.sh."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from app.config import settings, BASE_DIR

BACKUP_SCRIPT = BASE_DIR / "scripts" / "pg_backup.sh"


def _human_size(num_bytes: int) -> str:
    units = ("B", "KB", "MB", "GB", "TB")
    size = float(num_bytes)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{num_bytes} B"


def _backup_dir() -> Path:
    custom = os.getenv("POSTGRES_BACKUP_DIR")
    if custom:
        return Path(custom)
    return BASE_DIR / "backups" / "postgres"


def create_postgres_backup() -> dict:
    """
    Запускает pg_backup.sh и возвращает метаданные созданного файла.

    Raises:
        FileNotFoundError: скрипт бэкапа не найден
        RuntimeError: pg_backup.sh завершился с ошибкой или файл не создан
    """
    if not BACKUP_SCRIPT.is_file():
        raise FileNotFoundError(f"Скрипт бэкапа не найден: {BACKUP_SCRIPT}")

    backup_root = _backup_dir()
    backup_root.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["POSTGRES_BACKUP_DIR"] = str(backup_root)

    before = {
        p.name
        for p in backup_root.glob(f"{settings.POSTGRES_DB}_*.dump")
        if p.is_file()
    }

    try:
        result = subprocess.run(
            ["bash", str(BACKUP_SCRIPT)],
            capture_output=True,
            text=True,
            timeout=600,
            cwd=str(BASE_DIR),
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Таймаут создания бэкапа (>10 мин)") from exc

    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()

    if result.returncode != 0:
        detail = stderr or stdout or "Неизвестная ошибка pg_backup.sh"
        raise RuntimeError(detail)

    created = [
        p
        for p in backup_root.glob(f"{settings.POSTGRES_DB}_*.dump")
        if p.is_file() and p.name not in before
    ]
    if not created:
        created = sorted(
            backup_root.glob(f"{settings.POSTGRES_DB}_*.dump"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

    if not created:
        raise RuntimeError("Бэкап завершился, но файл .dump не найден")

    latest = max(created, key=lambda p: p.stat().st_mtime)
    size_bytes = latest.stat().st_size

    return {
        "status": "ok",
        "filename": latest.name,
        "path": str(latest.resolve()),
        "size_bytes": size_bytes,
        "size_human": _human_size(size_bytes),
        "message": stdout.splitlines()[-1] if stdout else f"Бэкап сохранён: {latest.name}",
    }
