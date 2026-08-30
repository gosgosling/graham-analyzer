"""
Правка дефектов, найденных `scripts.audit_data`.

Сюда попадают только те случаи, где верное значение выводится из самой базы,
без обращения к отчёту. Каждая правка несёт при себе доказательство — и оно
проверяется на месте, перед записью: если текущее значение в базе окажется не
тем, что описано в `broken`, правка не применится. Это защищает от повторного
запуска по уже исправленным данным и от правки не того, что имелось в виду.

    python -m scripts.fix_audit_defects            # показать, ничего не менять
    python -m scripts.fix_audit_defects --apply    # записать
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

from app.database import SessionLocal
from app.models.company import Company
from app.models.financial_report import FinancialReport


@dataclass(frozen=True)
class Fix:
    ticker: str
    year: int
    field: str
    broken: float
    correct: float
    why: str


# Газпром: во все остальные годы активы сходятся с обязательствами и капиталом
# копейка в копейку, так что сумма здесь — не догадка, а сам отчёт.
# 2015-й вдобавок ровно вдесятеро больше верного значения, 2018-й получил
# лишнюю цифру в середине и ложится между 18,2 и 21,9 трлн соседних лет.
GAZP = [
    Fix("GAZP", 2015, "total_assets", 170_520_400, 17_052_040,
        "6 137 418 + 10 914 622; ровно ÷10 от введённого"),
    Fix("GAZP", 2018, "total_assets", 208_210_440, 20_810_440,
        "7 034 287 + 13 776 153; между 18 238 770 (2017) и 21 882 348 (2019)"),
]

# Газпром нефть: у неё баланс в норме расходится на 4% из-за доли миноритариев,
# поэтому одна лишь сумма обязательств и капитала доказательством не была бы.
# Но введённое значение получается из неё выбрасыванием ровно одного нуля
# (2 930 008 → 293 008), и результат встаёт между соседними годами.
SIBN = [
    Fix("SIBN", 2017, "total_assets", 293_008, 2_930_008,
        "выпал ноль: 2 93[0]008; между 2 548 811 (2016) и 3 520 926 (2018)"),
]

# Башнефть: 2023 и 2024 сходятся ровно, потерян ведущий разряд.
# Обыкновенные и привилегированные — отдельные строки с одними и теми же
# цифрами отчёта, правим обе.
BANE = [
    Fix(ticker, 2025, "total_assets", 118_143, 1_118_143,
        "203 235 + 914 908; рядом 1 163 247 (2024)")
    for ticker in ("BANE", "BANEP")
]

FIXES = GAZP + SIBN + BANE


def main() -> int:
    apply = "--apply" in sys.argv
    db = SessionLocal()
    applied, skipped = 0, 0
    try:
        for fix in FIXES:
            company = db.query(Company).filter(Company.ticker == fix.ticker).one_or_none()
            report = None
            if company is not None:
                report = (
                    db.query(FinancialReport)
                    .filter(
                        FinancialReport.company_id == company.id,
                        FinancialReport.fiscal_year == fix.year,
                        FinancialReport.period_type == "ANNUAL",
                    )
                    .one_or_none()
                )
            if report is None:
                print(f"  ПРОПУСК  {fix.ticker} {fix.year}: отчёта нет")
                skipped += 1
                continue

            current = getattr(report, fix.field)
            current = None if current is None else float(current)
            if current is None or abs(current - fix.broken) > 1:
                print(f"  ПРОПУСК  {fix.ticker} {fix.year} {fix.field}: в базе "
                      f"{current:,.0f}, ожидалось {fix.broken:,.0f} — не трогаю"
                      .replace(",", " "))
                skipped += 1
                continue

            print(f"  {fix.ticker:<6}{fix.year}  {fix.field}: "
                  f"{fix.broken:>14,.0f} → {fix.correct:>14,.0f}".replace(",", " "))
            print(f"          {fix.why}")
            if apply:
                setattr(report, fix.field, fix.correct)
            applied += 1

        if apply:
            db.commit()
            print(f"\nЗаписано: {applied}, пропущено: {skipped}")
        else:
            db.rollback()
            print(f"\nК записи: {applied}, пропущено: {skipped}")
            print("Ничего не изменено. Чтобы записать: --apply")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
