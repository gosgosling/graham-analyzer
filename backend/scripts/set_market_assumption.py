"""Ввод допущений об уровне рынка и расчёт базового множителя.

Три из четырёх входных величин — суждение, а не измерение, поэтому у скрипта
нет умолчаний: безрисковую ставку, премию за риск и темп роста дивидендов
надо назвать явно, и лучше с припиской, откуда они взялись.

    # посмотреть, что будет при разных допущениях, ничего не записывая
    python -m scripts.set_market_assumption --grid

    # посчитать один набор
    python -m scripts.set_market_assumption --year 2026 \\
        --risk-free 14.5 --premium 5.0 --growth 6.0

    # записать
    python -m scripts.set_market_assumption --year 2026 \\
        --risk-free 14.5 --premium 5.0 --growth 6.0 \\
        --note "ОФЗ 26238 на 30.08.2026; премия — суждение" --apply

Выплата (`payout`) по умолчанию считается по базе: совокупные дивиденды
делятся на совокупную прибыль по компаниям, прошедшим аудит и помеченным
проверенными. Ручное значение задаётся через `--payout`.
"""

from __future__ import annotations

import argparse

from app.database import SessionLocal
from app.models.market_assumption import MarketAssumption
from app.services.analysis import market_snapshot
from app.services.analysis.market_multiple import (
    base_multiple,
    paired_multiples,
    sensitivity,
)

PAYOUT_YEAR = market_snapshot.DEFAULT_YEAR


def show(result, label: str) -> None:
    if result is None:
        return
    print(f"  {label}")
    print(f"    K = {result.risk_free_rate} + {result.risk_premium} = "
          f"{result.required_return}%   g = {result.dividend_growth}%   "
          f"зазор {result.spread} п.п.")
    if result.value is None:
        print(f"    МНОЖИТЕЛЬ НЕ СЧИТАЕТСЯ: {result.problem}")
        return
    fragile = "   ХРУПКО: ответ чувствителен к входу сильнее, чем к рынку" if result.fragile else ""
    print(f"    множитель {result.value}   доходность {result.earnings_yield}%{fragile}")


def grid(payout: float) -> None:
    """Сетка допущений: видно, чем ответ обязан ставке, а чем — суждению."""
    growths = (4.0, 6.0, 8.0)
    premiums = (4.0, 5.0, 6.0, 7.0)
    print(f"\nБазовый множитель при выплате {payout}%\n")
    for growth in growths:
        print(f"  рост дивидендов {growth}%")
        header = "    ОФЗ \\ премия" + "".join(f"{p:>9.0f}%" for p in premiums)
        print(header)
        for risk_free in (12.0, 13.0, 14.0, 15.0, 16.0):
            cells = []
            for premium in premiums:
                result = base_multiple(payout, risk_free, premium, growth)
                cells.append("        —" if result is None or result.value is None
                             else f"{result.value:>9.1f}")
            print(f"    {risk_free:>13.0f}%" + "".join(cells))
        print()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int)
    parser.add_argument("--risk-free", type=float, help="доходность длинных ОФЗ, %%")
    parser.add_argument("--normalized-risk-free", type=float,
                        help="та же ставка вне пика цикла, %%")
    parser.add_argument("--premium", type=float, help="премия за риск, п.п.")
    parser.add_argument("--growth", type=float,
                        help="рост дивидендов, %% (иначе устойчивый по базе)")
    parser.add_argument("--payout", type=float, help="выплата, %% (иначе по базе)")
    parser.add_argument("--long-run-growth", type=float,
                        help="потолок устойчивого роста компаний, %% годовых")
    parser.add_argument("--note", default=None)
    parser.add_argument("--grid", action="store_true", help="сетка допущений")
    parser.add_argument("--apply", action="store_true", help="записать в базу")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        snap = market_snapshot.snapshot(db)
        print(f"По базе за {PAYOUT_YEAR} ({snap.companies} компаний, "
              f"проверенных и без дефектов аудита):")
        print(f"  дивиденды {snap.total_dividends:,.0f} млн ₽ / "
              f"прибыль {snap.total_profit:,.0f} млн ₽".replace(",", " "))
        print(f"  выплата {snap.payout}%   отдача на капитал {snap.roe}%")
        print(f"  рынок торгуется по {snap.observed_multiple} прибыли")

        payout = args.payout if args.payout is not None else snap.payout
        if payout is None:
            print("Выплату определить не удалось — задайте --payout")
            return 1

        # Рост не угадывается: расти можно только на то, что не раздал.
        derived_growth = snap.growth
        if derived_growth is not None:
            print(f"  устойчивый рост = {snap.roe}% × (1 − {snap.payout}%) "
                  f"= {derived_growth}%")

        if args.grid:
            grid(payout)
            return 0

        growth = args.growth if args.growth is not None else derived_growth
        if None in (args.year, args.risk_free, args.premium) or growth is None:
            print("\nНужны --year, --risk-free, --premium "
                  "(рост берётся устойчивый, если не задан --growth). "
                  "Или --grid, чтобы просто посмотреть.")
            return 1

        print(f"\nГод {args.year}"
              f"   выплата {payout}%{' вручную' if args.payout is not None else ''}"
              f"   рост {growth}%{' вручную' if args.growth is not None else ' устойчивый'}")
        pair = paired_multiples(payout, args.risk_free, args.premium, growth,
                                args.normalized_risk_free)
        show(pair["current"], "при сегодняшней ставке")
        show(pair["normalized"], "если ставки нормализуются")
        if pair["rate_effect"]:
            print(f"  разница в {pair['rate_effect']}x — это про момент в цикле "
                  f"ставок, а не про компании")
        print(f"  для сравнения: США за 115 лет — 13,8 (пятилетки от 8,9 до 18,8)")
        if args.long_run_growth is not None:
            print(f"  потолок роста компаний: {args.long_run_growth}% — выше него "
                  f"выведенный рост подрезается")

        if pair["current"] is not None and pair["current"].value:
            print("  чувствительность к премии за риск:")
            for row in sensitivity(pair["current"]):
                value = (row["value"] if row["value"] is not None
                         else f"— ({row['problem'][:40]})")
                print(f"     премия {row['risk_premium']:>5}%  →  {value}")

        if not args.apply:
            print("\nНичего не записано. Чтобы записать: --apply")
            return 0

        row = db.get(MarketAssumption, args.year)
        if row is None:
            row = MarketAssumption(year=args.year)
            db.add(row)
        row.risk_free_rate = args.risk_free
        row.normalized_risk_free_rate = args.normalized_risk_free
        row.long_run_growth = args.long_run_growth
        row.risk_premium = args.premium
        row.dividend_growth = growth
        row.payout = args.payout
        row.note = args.note
        row.source = "manual"
        db.commit()
        print(f"\nЗаписано за {args.year} год.")
        if not args.note:
            print("Приписки нет — через полгода будет не понять, откуда числа.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
