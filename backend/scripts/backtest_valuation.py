"""Обратный тест оценки: пересекала ли полоса цену за полный цикл.

Гейт из гл. 4, с. 53: оценка, ни разу не совпавшая с ценой за цикл, неверна.
Проверяется модель, а не компании — если «ни разу» выпадает у большинства,
чинить надо формулу.

    python -m scripts.backtest_valuation             # проверенные компании
    python -m scripts.backtest_valuation --all       # все с историей
    python -m scripts.backtest_valuation --average   # уровень простой средней
    python -m scripts.backtest_valuation --compare   # средняя против тенденции
    python -m scripts.backtest_valuation LKOH GAZP   # выборочно, по годам
"""

from __future__ import annotations

import sys
from collections import Counter

from app.database import SessionLocal
from app.models.company import Company
from app.models.key_rate import KeyRate
from app.models.market_assumption import MarketAssumption
from app.services.analysis import market_snapshot
from app.services.analysis.valuation_backtest import (
    MIN_BACKTEST_YEARS,
    OFZ_OVER_KEY_RATE,
    backtest,
)


def main() -> int:
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    wanted = {a.upper() for a in sys.argv[1:] if not a.startswith("--")}

    db = SessionLocal()
    try:
        assumption = (
            db.query(MarketAssumption).order_by(MarketAssumption.year.desc()).first()
        )
        if assumption is None:
            print("Нет допущений об уровне рынка: scripts.set_market_assumption")
            return 1

        rates = {row.year: float(row.avg_rate) for row in db.query(KeyRate)}
        premium = float(assumption.risk_premium)
        cap = (
            float(assumption.long_run_growth)
            if assumption.long_run_growth is not None else None
        )

        if wanted:
            tickers = sorted(wanted)
        elif "--all" in flags:
            tickers = [str(c.ticker) for c in db.query(Company).order_by(Company.ticker)]
        else:
            tickers = market_snapshot.trustworthy_tickers(db)

        print(f"Премия за риск {premium}%, потолок роста {cap}%, "
              f"ставка = ключевая ЦБ + {OFZ_OVER_KEY_RATE} п.п.")
        print(f"Годы со ставкой: {min(rates)}–{max(rates)}\n")

        companies = [
            company for company in (
                db.query(Company).filter(Company.ticker == ticker).first()
                for ticker in tickers
            ) if company is not None
        ]

        if "--compare" in flags:
            _compare(db, companies, premium, rates, cap)
            return 0

        basis = "average" if "--average" in flags else "trend"
        print(f"Уровень: {'простая средняя' if basis == 'average' else 'линия тенденции'}\n")
        results = [
            backtest(db, company, premium, rates, growth_cap=cap, basis=basis)
            for company in companies
        ]

        if wanted:
            _print_years(results)
            return 0

        _print_summary(results)
        return 0
    finally:
        db.close()


def _compare(db, companies: list, premium: float, rates: dict, cap) -> None:
    """Средняя против тенденции — то, ради чего обратный тест и нужен.

    Проверять модель без возможности сравнить два варианта бессмысленно:
    цифра «44% попаданий» ничего не значит, пока не видно, что у другого
    способа их 28%.
    """
    print(f"{'уровень':<12}{'внутри':>8}{'выше':>7}{'ниже':>7}{'доля':>8}")
    for basis, label in (("average", "средняя"), ("trend", "тенденция")):
        inside = above = below = 0
        for company in companies:
            for row in backtest(db, company, premium, rates,
                                growth_cap=cap, basis=basis).counted:
                if row.inside:
                    inside += 1
                elif row.price > row.high:
                    above += 1
                else:
                    below += 1
        total = inside + above + below
        share = inside / total if total else 0
        print(f"{label:<12}{inside:>8}{above:>7}{below:>7}{share:>8.0%}")
    print()
    print("Смещение вверх у простой средней — тот самый дефект из табл. 30.3:")
    print("она занижает растущие компании, и оценка систематически ниже цены.")


def _print_years(results: list) -> None:
    for result in results:
        print(f"=== {result.ticker}   {result.verdict}"
              f"   попаданий {result.hits} из {len(result.counted)}")
        for year in result.years:
            if year.refused:
                print(f"   {year.year}  цена {year.price:>10,.1f}   ОТКАЗ: "
                      f"{year.refused[:52]}".replace(",", " "))
                continue
            mark = "внутри" if year.inside else ("ниже" if year.price < year.low else "выше")
            print(f"   {year.year}  цена {year.price:>10,.1f}   "
                  f"полоса {year.low:>10,.1f}–{year.high:<11,.1f} {mark:<7}"
                  f"×{year.distance}".replace(",", " "))
        print()


def _print_summary(results: list) -> None:
    verdicts = Counter(r.verdict for r in results)
    counted = [r for r in results if len(r.counted) >= MIN_BACKTEST_YEARS]

    print(f"{'':8}{'лет':>5}{'попаданий':>11}{'доля':>7}{'медиана откл.':>15}  приговор")
    for result in sorted(results, key=lambda r: -(r.hit_rate or -1)):
        if not result.counted:
            continue
        print(f"{result.ticker:<8}{len(result.counted):>5}{result.hits:>11}"
              f"{result.hit_rate if result.hit_rate is not None else 0:>7.2f}"
              f"{result.median_distance if result.median_distance else 0:>15.2f}"
              f"  {result.verdict}")

    print()
    print("ПРИГОВОР МОДЕЛИ:", dict(verdicts))
    if counted:
        total_years = sum(len(r.counted) for r in counted)
        total_hits = sum(r.hits for r in counted)
        never = sum(1 for r in counted if r.hits == 0)
        print(f"  компаний с достаточной историей: {len(counted)}")
        print(f"  из них ни разу не попали:        {never}")
        print(f"  попаданий всего:                 {total_hits} из {total_years} "
              f"({total_hits / total_years:.0%})")
        print()
        if never > len(counted) / 2:
            print("  Гейт НЕ пройден: у большинства компаний оценка ни разу не")
            print("  совпала с ценой. По гл. 4 это подозрение к модели, а не к рынку.")
        else:
            print("  Гейт пройден: у большинства компаний полоса хотя бы раз")
            print("  накрывала цену за цикл.")


if __name__ == "__main__":
    raise SystemExit(main())
