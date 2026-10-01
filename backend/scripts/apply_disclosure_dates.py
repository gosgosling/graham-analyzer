#!/usr/bin/env python3
"""Записывает фактические даты раскрытия в `financial_reports.disclosed_at`.

Даты собирает tools/edisclosure-scraper/fetch_disclosure_dates.py — это самая
ранняя публикация консолидированной отчётности МСФО за период на e-disclosure.
Поэтому пишутся только строки МСФО: у РСБУ своя дата.

Уже заполненные даты не трогаются (их мог поправить аналитик), если не
передан --force. Дата, которой быть не может, пропускается с сообщением:
раньше конца периода или позже чем через полтора года после него — это
повторная публикация, а не раскрытие.

Запуск из backend:
  venv/bin/python scripts/apply_disclosure_dates.py --dry-run
  venv/bin/python scripts/apply_disclosure_dates.py
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.database import SessionLocal  # noqa: E402
from app.models import Company  # noqa: E402
from app.models.financial_report import FinancialReport  # noqa: E402
from app.utils.disclosure import period_end  # noqa: E402

SOURCE = ROOT.parent / "tools" / "edisclosure-scraper" / "disclosure_dates.json"
MAX_DELAY = timedelta(days=540)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="показать, но не записывать")
    parser.add_argument("--force", action="store_true", help="перезаписать уже заполненные даты")
    args = parser.parse_args()

    listing = json.loads(SOURCE.read_text())
    db = SessionLocal()
    written = kept = skipped = 0
    try:
        for ticker, periods in sorted(listing.items()):
            company = db.query(Company).filter(Company.ticker == ticker).first()
            if company is None:
                continue
            for key, iso in periods.items():
                year = int(key.split("_")[0])
                kind = "SEMI_ANNUAL" if key.endswith("_H1") else "ANNUAL"
                day = date.fromisoformat(iso)
                end = period_end(year, kind)
                if not (end < day <= end + MAX_DELAY):
                    print(f"{ticker} {key}: {iso} — вне окна раскрытия, пропуск")
                    skipped += 1
                    continue
                rows = (
                    db.query(FinancialReport)
                    .filter(
                        FinancialReport.company_id == company.id,
                        FinancialReport.fiscal_year == year,
                        FinancialReport.period_type == kind,
                        FinancialReport.accounting_standard == "IFRS",
                    )
                    .all()
                )
                for row in rows:
                    if row.disclosed_at is not None and not args.force:
                        kept += 1
                        continue
                    row.disclosed_at = day
                    written += 1
        if args.dry_run:
            db.rollback()
        else:
            db.commit()
    finally:
        db.close()

    verb = "было бы записано" if args.dry_run else "записано"
    print(f"\n{verb}: {written}, оставлено как есть: {kept}, пропущено: {skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
