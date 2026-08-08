#!/usr/bin/env python3
"""Загрузка средней ключевой ставки ЦБ по годам.

Стоимость фондирования банка сравнивается со ставкой ТОГО ЖЕ периода:
12% годовых при ключевой 4% и при 19% означают противоположные вещи.
Поэтому нужен ряд по годам, а не текущее значение.

Источник — таблица на сайте ЦБ (https://www.cbr.ru/hd_base/KeyRate/).
Считается среднее арифметическое по дням, за которые ставка опубликована:
ЦБ печатает значение на каждый рабочий день, поэтому среднее по ним близко
к средневзвешенному по календарю.

Запуск из backend (раз в год, после закрытия года):
  venv/bin/python scripts/load_key_rates.py
  venv/bin/python scripts/load_key_rates.py --from-year 2015 --dry-run
"""
from __future__ import annotations

import argparse
import re
import ssl
import sys
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path
from typing import Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.database import SessionLocal  # noqa: E402
from app.models.key_rate import KeyRate  # noqa: E402

_URL = (
    "https://www.cbr.ru/hd_base/KeyRate/"
    "?UniDbQuery.Posted=True&UniDbQuery.From={frm}&UniDbQuery.To={to}"
)
# Строка таблицы: дата и ставка в соседних ячейках.
_ROW = re.compile(r"<td[^>]*>\s*(\d{2}\.\d{2}\.\d{4})\s*</td>\s*<td[^>]*>\s*([\d,\.]+)\s*</td>")


def fetch_year(year: int, timeout: int = 30) -> List[Tuple[str, float]]:
    """Дневные значения ставки за год: [(дата, ставка), ...]."""
    url = _URL.format(frm=f"01.01.{year}", to=f"31.12.{year}")
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    # Сертификат ЦБ подписан национальным УЦ, которого нет в системном хранилище
    # на большинстве машин: проверку отключаем осознанно — данные публичные,
    # и подмена курса ключевой ставки не создаёт угрозы.
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE

    with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
        html = response.read().decode("utf-8", "replace")

    return [(d, float(rate.replace(",", "."))) for d, rate in _ROW.findall(html)]


def average_rate(rows: List[Tuple[str, float]]) -> float:
    return round(sum(rate for _d, rate in rows) / len(rows), 2)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-year", type=int, default=2013, help="с какого года грузить")
    parser.add_argument("--to-year", type=int, default=date.today().year, help="по какой год")
    parser.add_argument("--dry-run", action="store_true", help="показать, но не сохранять")
    args = parser.parse_args()

    loaded: Dict[int, float] = {}
    for year in range(args.from_year, args.to_year + 1):
        try:
            rows = fetch_year(year)
        except (urllib.error.URLError, TimeoutError) as exc:
            print(f"{year}: не удалось загрузить — {exc}", file=sys.stderr)
            continue
        if not rows:
            print(f"{year}: данных нет (ставка введена в 2013 году)")
            continue
        loaded[year] = average_rate(rows)
        print(f"{year}: средняя {loaded[year]:.2f}%  (дней с данными: {len(rows)})")

    if not loaded:
        print("Ничего не загружено", file=sys.stderr)
        return 1

    if args.dry_run:
        print("\n--dry-run: в базу не записано")
        return 0

    db = SessionLocal()
    try:
        for year, rate in loaded.items():
            existing = db.query(KeyRate).filter(KeyRate.year == year).first()
            if existing:
                existing.avg_rate = rate
                existing.source = "cbr"
            else:
                db.add(KeyRate(year=year, avg_rate=rate, source="cbr"))
        db.commit()
    finally:
        db.close()

    print(f"\nСохранено лет: {len(loaded)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
