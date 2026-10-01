#!/usr/bin/env python3
"""Загрузка средней ключевой ставки ЦБ по годам.

Стоимость фондирования банка сравнивается со ставкой ТОГО ЖЕ периода:
12% годовых при ключевой 4% и при 19% означают противоположные вещи.
Поэтому нужен ряд по годам, а не текущее значение.

Источник — таблица на сайте ЦБ (https://www.cbr.ru/hd_base/KeyRate/).
Считается среднее арифметическое по дням, за которые ставка опубликована:
ЦБ печатает значение на каждый рабочий день, поэтому среднее по ним близко
к средневзвешенному по календарю.

Текущий год докачивается сам — ежедневным планировщиком. Скрипт нужен, чтобы
загрузить историю целиком.

Запуск из backend:
  venv/bin/python scripts/load_key_rates.py
  venv/bin/python scripts/load_key_rates.py --from-year 2015 --dry-run
"""
from __future__ import annotations

import argparse
import sys
import urllib.error
from datetime import date
from pathlib import Path
from typing import Dict

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.database import SessionLocal  # noqa: E402
from app.services.market.key_rate_service import (  # noqa: E402
    average_rate,
    fetch_year,
    store_year,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-year", type=int, default=2013, help="с какого года грузить")
    parser.add_argument("--to-year", type=int, default=date.today().year, help="по какой год")
    parser.add_argument("--dry-run", action="store_true", help="показать, но не сохранять")
    args = parser.parse_args()

    loaded: Dict[int, list] = {}
    for year in range(args.from_year, args.to_year + 1):
        try:
            rows = fetch_year(year)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            print(f"{year}: не удалось загрузить — {exc}", file=sys.stderr)
            continue
        if not rows:
            print(f"{year}: данных нет (ставка введена в 2013 году)")
            continue
        loaded[year] = rows
        print(f"{year}: средняя {average_rate(rows):.2f}%  (дней с данными: {len(rows)})")

    if not loaded:
        print("Ничего не загружено", file=sys.stderr)
        return 1

    if args.dry_run:
        print("\n--dry-run: в базу не записано")
        return 0

    # Сохраняются и дни, и средняя за год: оценке на графике нужна ставка того
    # дня, а сравнению стоимости фондирования банка — средняя за тот же год.
    db = SessionLocal()
    try:
        for year, rows in loaded.items():
            store_year(db, year, rows)
    finally:
        db.close()

    print(f"\nСохранено лет: {len(loaded)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
