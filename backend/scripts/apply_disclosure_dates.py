#!/usr/bin/env python3
"""Записывает фактические даты раскрытия в `financial_reports.disclosed_at`.

Даты собирает tools/edisclosure-scraper/fetch_disclosure_dates.py — это самая
ранняя публикация консолидированной отчётности МСФО за период на e-disclosure.
Поэтому пишутся только строки МСФО: у РСБУ своя дата.

Уже заполненные даты не трогаются (их мог поправить аналитик), если не
передан --force. Дата, которой быть не может, пропускается с сообщением:
раньше конца периода или позже чем через полтора года после него — это
повторная публикация, а не раскрытие.

**Пропущенные годы.** В 2022–2023 многие компании МСФО за 2022 год не
публиковали вовсе: цифры 2022-го рынок увидел сравнительной колонкой в отчёте
за 2023, весной 2024-го. В базе у такой строки даты нет, и правило «конец года
+ 120 дней» считало её известной с апреля 2023-го — заглядывание вперёд почти
на год. Второй проход ставит таким строкам дату отчёта за следующий год (или
собственную, если она раньше: АЛРОСА выложила 2022 год только в августе 2024-го,
позже отчёта за 2023). Только там, где перечень компании на e-disclosure
покрывает этот год — иначе отсутствие отчёта значит лишь, что перечень
начинается позже (Мосбиржа), а не что отчёта не было.

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
        gaps = fill_gaps(db, listing, force=args.force)
        written += gaps
        if args.dry_run:
            db.rollback()
        else:
            db.commit()
    finally:
        db.close()

    verb = "было бы записано" if args.dry_run else "записано"
    print(f"\n{verb}: {written}, оставлено как есть: {kept}, пропущено: {skipped}")
    return 0


# Год, когда раскрытие массово прекращали: постановление №1102 разрешило не
# публиковать отчётность, и за 2022 год МСФО отдельно не вышла у Лукойла,
# Новатэка, Роснефти, Северстали и многих других. Ранние годы сюда не входят:
# e-disclosure начал хранить файлы около 2012-го, и даты загрузки 2008–2011
# годов — это время выкладки архива, а не раскрытия.
GAP_YEARS = {2022}
# Отчитывались за рубежом (Nasdaq, NYSE, Euronext): МСФО за 2022 вышла там в
# срок, а на e-disclosure появилась только после редомициляции.
FOREIGN_FILERS = {"OZON", "X5", "HEAD", "CNRU"}


def fill_gaps(db, listing: dict, *, force: bool = False) -> int:
    """Годовым строкам без даты, чей год компания отдельно не раскрыла, —
    дата отчёта за следующий год, где эти цифры впервые стали публичными."""
    written = 0
    for ticker, periods in sorted(listing.items()):
        if ticker in FOREIGN_FILERS:
            continue
        company = db.query(Company).filter(Company.ticker == ticker).first()
        if company is None or not periods:
            continue
        first_year = min(int(key.split("_")[0]) for key in periods)
        rows = (
            db.query(FinancialReport)
            .filter(
                FinancialReport.company_id == company.id,
                FinancialReport.period_type == "ANNUAL",
                FinancialReport.accounting_standard == "IFRS",
            )
            .all()
        )
        for row in rows:
            if row.disclosed_at is not None and not force:
                continue
            year = int(row.fiscal_year)
            if year not in GAP_YEARS:
                continue
            if year < first_year:
                continue  # перечень начинается позже — о раскрытии этого года он молчит
            own = periods.get(str(year))
            nxt = periods.get(str(year + 1))
            if not nxt:
                continue
            nxt_day = date.fromisoformat(nxt)
            if not (period_end(year + 1, "ANNUAL") < nxt_day <= period_end(year + 1, "ANNUAL") + MAX_DELAY):
                continue  # и следующий отчёт выложен с опозданием — опереться не на что
            candidates = [nxt_day]
            if own:
                candidates.append(date.fromisoformat(own))
            day = min(candidates)
            if own and day == date.fromisoformat(own) and day <= period_end(year, "ANNUAL") + MAX_DELAY:
                continue  # собственная дата в окне — её записал первый проход
            if not (period_end(year, "ANNUAL") < day):
                continue
            print(f"{ticker} {year}: отдельно не раскрыт, цифры — из отчёта за {year + 1} → {day}")
            row.disclosed_at = day
            written += 1
    return written


if __name__ == "__main__":
    raise SystemExit(main())
