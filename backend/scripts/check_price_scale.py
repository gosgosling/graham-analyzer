"""Цены и дробления: привести историю к шкале «как торговалось» и найти
скачки, которых не объясняет ни одно записанное дробление.

    python -m scripts.check_price_scale            # показать, ничего не меняя
    python -m scripts.check_price_scale --apply    # исправить

Скачок больше чем в три раза за день без дробления — это либо дробление,
которого нет в справочнике (добавить в companies.share_splits), либо смесь
шкал, которую ремонт не распознал. И то и другое смотреть глазами.
"""
from __future__ import annotations

import argparse
import sys

from app.database import SessionLocal
from app.models.company import Company
from app.models.stock_price import StockPrice
from app.services.market.split_scale import repair_company_prices, unexplained_jumps
from app.services.share_splits import company_splits


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="записать исправления")
    args = parser.parse_args()

    db = SessionLocal()
    problems = 0
    try:
        for company in db.query(Company).order_by(Company.ticker).all():
            splits = company_splits(db, company)
            fixed = repair_company_prices(db, company, dry_run=not args.apply) if splits else 0
            if fixed:
                verb = "исправлено" if args.apply else "к исправлению"
                print(f"{company.ticker:8} дробления {[(s['date'], s['ratio']) for s in splits]}: {verb} строк {fixed}")
            rows = [(r.date, float(r.price)) for r in
                    db.query(StockPrice).filter(StockPrice.company_id == company.id).order_by(StockPrice.date)]
            if fixed and not args.apply:
                continue  # до исправления скачки ожидаемы
            jumps = unexplained_jumps(rows, splits)
            if jumps:
                problems += 1
                shown = ", ".join(f"{d} ×{c}" for d, c in jumps[:5])
                print(f"{company.ticker:8} скачки без дробления: {shown}{' …' if len(jumps) > 5 else ''}")
    finally:
        db.close()
    print("Готово." if not problems else f"Компаний со скачками без дробления: {problems}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
