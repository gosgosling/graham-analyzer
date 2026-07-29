#!/usr/bin/env python3
"""Аудит покрытия базы: по каким компаниям реально можно считать Грэма.

«Отчёт загружен» и «по компании можно построить график» — разные вещи. Graham
Number требует equity + прибыль + акции + цену за каждый год, NCAV — оборотные
активы + обязательства + акции. Если поле пустое, год выпадает из графика, и
узнать об этом лучше сейчас, а не когда экран окажется пустым.

Скрипт только читает базу и ничего в ней не меняет.

Запуск из backend:
  venv/bin/python scripts/db_coverage_audit.py
  venv/bin/python scripts/db_coverage_audit.py --min-years 5 --out ../docs/DB-COVERAGE.md
"""
from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.database import SessionLocal  # noqa: E402
from app.models.company import Company  # noqa: E402
from app.models.enums import PeriodType  # noqa: E402
from app.models.financial_report import FinancialReport  # noqa: E402
from app.services.analysis.sector_profiles import resolve_profile  # noqa: E402
from app.services.analysis.share_counts import (  # noqa: E402
    resolve_shares_for_multipliers,
)

# Если в .env включён SQL_ECHO, SQL каждой строки затопил бы отчёт.
# Уровень сбрасывается после импорта: create_engine(echo=True) выставляет его сам.
logging.getLogger("sqlalchemy.engine.Engine").setLevel(logging.WARNING)


@dataclass
class YearState:
    """Что известно про один годовой отчёт компании."""
    year: int
    verified: bool
    has_price: bool
    graham_number_ready: bool
    ncav_ready: bool
    missing: List[str] = field(default_factory=list)


@dataclass
class CompanyState:
    ticker: str
    name: str
    profile: str
    years: List[YearState]

    @property
    def year_numbers(self) -> List[int]:
        return sorted(y.year for y in self.years)

    @property
    def span(self) -> str:
        nums = self.year_numbers
        return f"{nums[0]}–{nums[-1]}" if nums else "—"

    @property
    def gaps(self) -> List[int]:
        nums = self.year_numbers
        if not nums:
            return []
        return [y for y in range(nums[0], nums[-1] + 1) if y not in set(nums)]

    @property
    def unverified(self) -> int:
        return sum(1 for y in self.years if not y.verified)

    def longest_streak(self, predicate) -> int:
        """Максимум идущих подряд лет, удовлетворяющих условию."""
        ok_years = sorted(y.year for y in self.years if predicate(y))
        best = streak = 0
        prev: Optional[int] = None
        for year in ok_years:
            streak = streak + 1 if prev is not None and year == prev + 1 else 1
            best = max(best, streak)
            prev = year
        return best


def _num(value) -> Optional[float]:
    """Numeric из БД приходит Decimal; ноль здесь равнозначен отсутствию."""
    if value is None:
        return None
    val = float(value)
    return val if val != 0 else None


def _year_state(report: FinancialReport) -> YearState:
    equity = _num(report.equity)
    profit = _num(report.net_income) or _num(report.net_income_reported)
    shares = resolve_shares_for_multipliers(report)
    price = _num(report.price_per_share)
    current_assets = _num(report.current_assets)
    total_liabilities = _num(report.total_liabilities)

    missing = [
        name
        for name, value in (
            ("equity", equity),
            ("net_income", profit),
            ("shares", shares),
            ("price", price),
            ("current_assets", current_assets),
            ("total_liabilities", total_liabilities),
        )
        if value is None
    ]

    return YearState(
        year=int(report.fiscal_year),
        verified=bool(report.verified_by_analyst),
        has_price=price is not None,
        # Graham Number = √(22.5 × EPS × BVPS): нужны прибыль, капитал и акции.
        # Цена не входит в саму формулу, но без неё нет запаса прочности.
        graham_number_ready=None not in (equity, profit, shares) and price is not None,
        ncav_ready=None not in (current_assets, total_liabilities, shares),
        missing=missing,
    )


def _collect(db, report_type: str) -> List[CompanyState]:
    companies = db.query(Company).all()
    by_id: Dict[int, Company] = {c.id: c for c in companies}

    reports: Sequence[FinancialReport] = (
        db.query(FinancialReport)
        .filter(FinancialReport.period_type == PeriodType.ANNUAL)
        .order_by(FinancialReport.company_id, FinancialReport.fiscal_year)
        .all()
    )

    grouped: Dict[int, List[FinancialReport]] = {}
    for report in reports:
        grouped.setdefault(int(report.company_id), []).append(report)

    states: List[CompanyState] = []
    for company_id, company_reports in grouped.items():
        company = by_id.get(company_id)
        if company is None:
            continue
        kinds = {str(r.report_type or "general") for r in company_reports}
        if report_type != "all" and report_type not in kinds:
            continue
        profile = resolve_profile(
            company.sector,
            next(iter(kinds)) if len(kinds) == 1 else "general",
            company.sector_profile_key,
        )
        # На год может быть несколько отчётов (МСФО/РСБУ) — берём последний.
        latest_per_year: Dict[int, FinancialReport] = {}
        for report in company_reports:
            latest_per_year[int(report.fiscal_year)] = report
        states.append(
            CompanyState(
                ticker=company.ticker,
                name=company.name,
                profile=profile.label,
                years=[_year_state(r) for r in latest_per_year.values()],
            )
        )
    return states


def _company_table(states: List[CompanyState], min_years: int) -> List[str]:
    lines = [
        "| Тикер | Профиль | Годы | Лет | Подряд | Graham Number | NCAV | Без цены | Не сверено |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for state in states:
        gn = state.longest_streak(lambda y: y.graham_number_ready)
        ncav = state.longest_streak(lambda y: y.ncav_ready)
        no_price = sum(1 for y in state.years if not y.has_price)
        mark = "" if gn >= min_years else " ⚠"
        lines.append(
            f"| **{state.ticker}**{mark} | {state.profile} | {state.span} | "
            f"{len(state.years)} | {state.longest_streak(lambda y: True)} | "
            f"{gn} | {ncav} | {no_price} | {state.unverified} |"
        )
    return lines


def _missing_field_stats(states: List[CompanyState]) -> List[str]:
    counts: Dict[str, int] = {}
    total_years = 0
    for state in states:
        for year in state.years:
            total_years += 1
            for name in year.missing:
                counts[name] = counts.get(name, 0) + 1
    if total_years == 0:
        return ["- нет годовых отчётов"]
    return [
        f"- `{name}` — пусто в {count} из {total_years} лет ({count / total_years:.0%})"
        for name, count in sorted(counts.items(), key=lambda kv: -kv[1])
    ] or ["- пусто: все поля заполнены"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--min-years",
        type=int,
        default=5,
        help="сколько лет подряд нужно компании, чтобы считаться готовой к показу",
    )
    parser.add_argument("--out", help="записать отчёт в markdown-файл")
    parser.add_argument(
        "--report-type",
        default="all",
        choices=("all", "general", "bank"),
        help="ограничить выборку типом отчётов",
    )
    parser.add_argument(
        "--limit", type=int, help="показать только N лучших компаний в таблице"
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        states = _collect(db, args.report_type)
    finally:
        db.close()

    if not states:
        print("В базе нет годовых отчётов", file=sys.stderr)
        return 1

    states.sort(
        key=lambda s: (
            -s.longest_streak(lambda y: y.graham_number_ready),
            -len(s.years),
            s.ticker,
        )
    )
    ready = [s for s in states if s.longest_streak(lambda y: y.graham_number_ready) >= args.min_years]
    ncav_ready = [s for s in states if s.longest_streak(lambda y: y.ncav_ready) >= args.min_years]
    total_years = sum(len(s.years) for s in states)
    unverified = sum(s.unverified for s in states)
    with_gaps = [s for s in states if s.gaps]

    profiles: Dict[str, int] = {}
    for state in states:
        profiles[state.profile] = profiles.get(state.profile, 0) + 1

    shown = states[: args.limit] if args.limit else states

    lines = [
        "# Покрытие базы: готовность к расчётам по Грэму",
        "",
        f"Порог показа — **{args.min_years} лет подряд**.",
        "",
        "| Метрика | Значение |",
        "| --- | --- |",
        f"| Компаний с годовыми отчётами | **{len(states)}** |",
        f"| Годовых отчётов | **{total_years}** |",
        f"| Не сверено аналитиком | **{unverified}** |",
        f"| Готовы к Graham Number (≥{args.min_years} лет подряд) | **{len(ready)}** |",
        f"| Готовы к NCAV (≥{args.min_years} лет подряд) | **{len(ncav_ready)}** |",
        f"| С дырами в годах | **{len(with_gaps)}** |",
        "",
        "## Отраслевые профили",
        "",
        *[f"- {label}: {count}" for label, count in sorted(profiles.items(), key=lambda kv: -kv[1])],
        "",
        "## Компании",
        "",
        "«Подряд» — максимум идущих подряд лет; ⚠ — не дотягивает до порога.",
        "",
        *_company_table(shown, args.min_years),
        "",
        "## Чего не хватает в годовых отчётах",
        "",
        *_missing_field_stats(states),
        "",
    ]
    if with_gaps:
        lines += [
            "## Дыры в годах",
            "",
            *[f"- {s.ticker}: нет {', '.join(str(y) for y in s.gaps)}" for s in with_gaps],
            "",
        ]

    text = "\n".join(lines)
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
        print(f"\n→ {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
