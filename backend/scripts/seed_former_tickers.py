"""
Проставляет известные переименования и дробления акций.

Запуск:
    python -m scripts.seed_former_tickers          # показать, что будет сделано
    python -m scripts.seed_former_tickers --apply  # записать

Уже заполненные компании не трогает: справочник в коде — стартовая заготовка,
а правка руками важнее. Переименования продолжаются, и рано или поздно
понадобится вписать то, чего в справочнике нет.
"""

from __future__ import annotations

import argparse
import sys

from app.database import SessionLocal
from app.models.company import Company
from app.services.share_splits import KNOWN_SPLITS
from app.services.ticker_history import KNOWN_TICKER_CHANGES, describe_chain


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="записать изменения в БД")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        companies = (
            db.query(Company)
            .filter(Company.ticker.in_(list(KNOWN_TICKER_CHANGES)))
            .order_by(Company.ticker)
            .all()
        )
        if not companies:
            print("Ни одной компании из справочника в базе нет.")
            return 0

        changed = 0
        for company in companies:
            if company.former_tickers:
                print(f"{company.ticker:<6} уже заполнено: "
                      f"{describe_chain(str(company.ticker), company.former_tickers)}")
                continue
            entries = [dict(e) for e in KNOWN_TICKER_CHANGES[str(company.ticker)]]
            print(f"{company.ticker:<6} → {describe_chain(str(company.ticker), entries)}")
            if args.apply:
                company.former_tickers = entries
            changed += 1

        # Дробления — тем же проходом: обе таблицы описывают, чем бумага была
        # раньше, и заполняются в один момент.
        for company in (
            db.query(Company)
            .filter(Company.ticker.in_(list(KNOWN_SPLITS)))
            .order_by(Company.ticker)
            .all()
        ):
            if company.share_splits:
                print(f"{company.ticker:<6} дробления уже заполнены")
                continue
            entries = [dict(e) for e in KNOWN_SPLITS[str(company.ticker)]]
            for entry in entries:
                print(f"{company.ticker:<6} дробление {entry['ratio']:g}:1 с {entry['date']}")
            if args.apply:
                company.share_splits = entries
            changed += 1

        if args.apply and changed:
            db.commit()
            print(f"\nЗаписано компаний: {changed}")
        elif changed:
            print(f"\nБудет изменено: {changed}. Повторите с --apply.")
        else:
            print("\nВсё уже заполнено.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
