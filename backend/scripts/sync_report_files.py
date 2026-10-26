"""
Собирает хранилище исходных PDF отчётов и, по желанию, выкладывает его на сервер.

Сайт отдаёт на скачивание тот самый файл, из которого разобран отчёт
(`financial_reports.source_pdf_path`). Скрипт:

1. берёт из базы все отчёты с путём к PDF и группирует их по файлу;
2. раскладывает файлы в каталог хранилища под понятными именами —
   `LKOH/LKOH_2025.pdf`, `LKOH/LKOH_2026_H1.pdf` (жёсткими ссылками, без копий,
   если каталог на том же диске);
3. считает размер и SHA-256 и пишет `manifest.json` — по нему бэкенд узнаёт,
   у какого отчёта есть файл (см. `app/services/reports/report_files.py`);
4. с `--push` отправляет каталог на сервер через rsync.

Сумма пересчитывается, только если файл сменился: прошлый манифест хранит
размер и время изменения каждого исходника.

    python -m scripts.sync_report_files                       # собрать локально
    python -m scripts.sync_report_files --push ubuntu@host:/opt/graham/report-files
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

from app.database import SessionLocal
from app.models.company import Company
from app.models.financial_report import FinancialReport
from app.services.reports.report_files import MANIFEST, files_dir, report_key


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _period_suffix(report: FinancialReport) -> str:
    kind = str(getattr(report.period_type, "value", report.period_type)).upper()
    if kind == "SEMI_ANNUAL":
        return "_H1"
    if kind == "QUARTERLY":
        return f"_{(report.fiscal_quarter or 1) * 3}M"
    return ""


def _place(source: Path, target: Path) -> None:
    """Жёсткая ссылка, если можно; иначе копия. Старый файл заменяется."""
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()
    try:
        os.link(source, target)
    except OSError:
        shutil.copy2(source, target)


def build(stage: Path, reports_root: Path) -> dict:
    db = SessionLocal()
    try:
        tickers = {c.id: (c.ticker or f"ID{c.id}") for c in db.query(Company)}
        reports = (
            db.query(FinancialReport)
            .order_by(FinancialReport.fiscal_year, FinancialReport.report_date)
            .all()
        )
    finally:
        db.close()

    # Отчёт связан с файлом путём из разбора. Где пути нет (вносили вручную,
    # до появления поля), берём файл архива по соглашению об именах —
    # «LKOH/LKOH_2025.pdf», «LKOH/LKOH_2026_H1.pdf» — и только для МСФО:
    # годовой РСБУ лежал бы под тем же именем.
    by_file: dict[str, list] = defaultdict(list)
    by_name: dict[str, list] = defaultdict(list)
    for report in reports:
        if report.source_pdf_path:
            by_file[report.source_pdf_path].append(report)
            continue
        standard = str(getattr(report.accounting_standard, "value", report.accounting_standard)).upper()
        if standard != "IFRS":
            continue
        ticker = tickers.get(report.company_id, "")
        guess = f"{ticker}/{ticker}_{report.fiscal_year}{_period_suffix(report)}.pdf"
        if ticker and (reports_root / guess).is_file():
            by_name[guess].append(report)

    previous = {}
    old_manifest = stage / MANIFEST
    if old_manifest.exists():
        old = json.loads(old_manifest.read_text(encoding="utf-8"))
        previous = {**old.get("files", {}), **old.get("by_name", {})}

    files: dict[str, dict] = {}
    named: dict[str, dict] = {}
    by_report: dict[str, str] = {}
    taken: set[str] = set()
    missing = []

    def add(key: str, source: Path, group: list) -> dict:
        # Имя — по самому раннему отчёту из файла: годовой и полугодовой
        # почти никогда не делят PDF, а если делят — главный тот, что раньше.
        first = group[0]
        ticker = re.sub(r"[^A-Za-z0-9_-]+", "_", tickers.get(first.company_id, "X"))
        base = f"{ticker}_{first.fiscal_year}{_period_suffix(first)}"
        ext = source.suffix.lower() or ".pdf"
        name, n = f"{ticker}/{base}{ext}", 2
        while name in taken:
            name, n = f"{ticker}/{base}_{n}{ext}", n + 1
        taken.add(name)

        stat = source.stat()
        old = previous.get(key)
        if old and old.get("size") == stat.st_size and old.get("mtime") == int(stat.st_mtime) and old.get("sha256"):
            sha = old["sha256"]
        else:
            sha = _sha256(source)
        _place(source, stage / name)
        return {"path": name, "size": stat.st_size, "mtime": int(stat.st_mtime), "sha256": sha}

    for source_path, group in sorted(by_file.items()):
        source = Path(source_path)
        if not source.is_absolute():
            # Часть путей записана от корня архива: «CHMF/CHMF_2020_H1.pdf».
            source = reports_root / source
        if not source.is_file():
            missing.append(source_path)
            continue
        files[source_path] = add(source_path, source, group)

    for guess, group in sorted(by_name.items()):
        named[guess] = add(guess, reports_root / guess, group)
        for report in group:
            by_report[report_key(report.company_id, report.fiscal_year, report.period_type)] = guess

    # Файлы, на которые отчёты больше не ссылаются, из хранилища убираются.
    keep = {entry["path"] for entry in (*files.values(), *named.values())} | {MANIFEST}
    for path in stage.rglob("*"):
        if path.is_file() and str(path.relative_to(stage)) not in keep:
            path.unlink()

    manifest = {"files": files, "by_name": named, "reports": by_report}
    old_manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    size = sum(entry["size"] for entry in (*files.values(), *named.values()))
    linked = sum(len(by_file[p]) for p in files) + len(by_report)
    print(f"файлов: {len(files) + len(named)} (по пути из разбора {len(files)}, по имени {len(named)}), "
          f"отчётов с файлом: {linked} из {len(reports)}, объём: {size / 1e9:.2f} ГБ, "
          f"нет на диске: {len(missing)}")
    for path in missing:
        print(f"  нет файла: {path}")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--stage", type=Path, default=None, help="каталог хранилища (по умолчанию REPORT_FILES_DIR)")
    parser.add_argument("--root", type=Path, default=Path.home() / "Reports",
                        help="архив PDF, от которого считаются относительные пути")
    parser.add_argument("--push", help="куда выложить rsync'ом: user@host:/путь")
    args = parser.parse_args()

    stage = args.stage or files_dir()
    stage.mkdir(parents=True, exist_ok=True)
    build(stage, args.root)

    if args.push:
        # Манифест — последним: пока файлы едут, сайт ссылается только на те,
        # что уже лежат на сервере.
        common = ["rsync", "-a", "--info=stats1", "--chmod=D755,F644"]
        subprocess.run([*common, "--delete", f"--exclude={MANIFEST}", f"{stage}/", args.push], check=True)
        subprocess.run([*common, str(stage / MANIFEST), f"{args.push.rstrip('/')}/{MANIFEST}"], check=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
