"""Исходные PDF отчётов на скачивание.

Каждое число на сайте ведёт к отчёту, из которого взято, — но до сих пор
только названием. Проверить его мог лишь тот, кто сам найдёт PDF на сайте
компании или в e-disclosure, а компании их переносят и удаляют. Своя копия
закрывает этот разрыв: нажал на число — скачал тот самый файл.

Файлы лежат в `REPORT_FILES_DIR` вне базы и вне образа: их раздаёт Caddy по
адресу `/files/reports/…`, бэкенд их не читает. Он знает о них только из
`manifest.json`, который пишет `scripts/sync_report_files.py`:

    {"files":   {"<source_pdf_path>": {"path": "UPRO/UPRO_2025.pdf",
                                       "size": 3145728, "sha256": "…"}},
     "by_name": {"LKOH/LKOH_2025.pdf": {...}},
     "reports": {"<company_id>:2025:ANNUAL": "LKOH/LKOH_2025.pdf"}}

Ключ первой таблицы — `financial_reports.source_pdf_path` как есть: по нему
отчёт и файл связаны с момента разбора. У отчётов, внесённых без пути, файл
найден в архиве по имени, и связь идёт через компанию, год и период. Контрольная
сумма отдаётся вместе с адресом — любой может убедиться, что файл не подменён
между разбором и скачиванием.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Optional

from app.config import BASE_DIR, settings

PUBLIC_PREFIX = "/files/reports/"
MANIFEST = "manifest.json"

_lock = threading.Lock()
_cache: dict = {"mtime": None, "data": {}}


def files_dir() -> Path:
    return Path(settings.REPORT_FILES_DIR) if settings.REPORT_FILES_DIR else BASE_DIR / "data" / "report-files"


def report_key(company_id: int, fiscal_year: int, period_type) -> str:
    kind = str(getattr(period_type, "value", period_type)).upper()
    return f"{company_id}:{fiscal_year}:{kind}"


def _manifest() -> dict:
    """Манифест с диска; перечитывается, только когда файл сменился."""
    path = files_dir() / MANIFEST
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {}
    with _lock:
        if _cache["mtime"] != mtime:
            try:
                _cache["data"] = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                _cache["data"] = {}
            _cache["mtime"] = mtime
        return _cache["data"]


def report_file(source_pdf_path: Optional[str], company_id: Optional[int] = None,
                fiscal_year: Optional[int] = None, period_type=None) -> Optional[dict]:
    """Адрес, размер и SHA-256 копии отчёта; `None`, если копии нет."""
    manifest = _manifest()
    entry = manifest.get("files", {}).get(source_pdf_path) if source_pdf_path else None
    if entry is None and company_id is not None and fiscal_year is not None and period_type is not None:
        name = manifest.get("reports", {}).get(report_key(company_id, fiscal_year, period_type))
        entry = manifest.get("by_name", {}).get(name) if name else None
    if not entry or not entry.get("path"):
        return None
    return {
        "url": PUBLIC_PREFIX + entry["path"],
        "size": entry.get("size"),
        "sha256": entry.get("sha256"),
    }
