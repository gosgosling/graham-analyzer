"""Разбор строки «Отчётный период» с e-disclosure → period_type / year / quarter."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

_YEAR = re.compile(r"(20\d{2}|19\d{2})")


@dataclass(frozen=True)
class ParsedPeriod:
    period_type: str  # annual | quarterly | semi_annual
    fiscal_year: int
    fiscal_quarter: Optional[int]  # 1/3 for quarterly; None otherwise
    period_key: str  # 2024 | 2026_Q1 | 2026_H1
    interim_rank: int  # 0=annual, 1=Q1, 2=H1, 3=Q3


def period_key(
    period_type: str, fiscal_year: int, fiscal_quarter: Optional[int]
) -> str:
    if period_type == "annual":
        return str(fiscal_year)
    if period_type == "semi_annual":
        return f"{fiscal_year}_H1"
    if period_type == "quarterly" and fiscal_quarter:
        return f"{fiscal_year}_Q{fiscal_quarter}"
    return str(fiscal_year)


def parse_period_label(period: str) -> Optional[ParsedPeriod]:
    """
    Примеры:
      2024 → annual
      2026, 3 месяца / 1 квартал → Q1
      2025, 6 месяцев → H1 (semi_annual)
      2025, 9 месяцев → Q3
    """
    if not period:
        return None
    text = period.strip().lower().replace("ё", "е")
    ym = _YEAR.search(text)
    if not ym:
        return None
    year = int(ym.group(1))

    # Только год
    if re.fullmatch(r"\d{4}", period.strip()):
        return ParsedPeriod("annual", year, None, str(year), 0)

    # Кварталы / месяцы
    if re.search(r"\b1\s*квартал\b|\b3\s*месяц", text) or re.search(
        r"\bq1\b|first\s+quarter", text
    ):
        return ParsedPeriod("quarterly", year, 1, f"{year}_Q1", 1)
    if re.search(r"\b2\s*квартал\b|\b6\s*месяц|\bполугод", text) or re.search(
        r"\bh1\b|semi[- ]?annual|half[- ]?year", text
    ):
        return ParsedPeriod("semi_annual", year, None, f"{year}_H1", 2)
    if re.search(r"\b3\s*квартал\b|\b9\s*месяц", text) or re.search(
        r"\bq3\b|nine\s+month", text
    ):
        return ParsedPeriod("quarterly", year, 3, f"{year}_Q3", 3)
    if re.search(r"\b4\s*квартал\b|\b12\s*месяц|\bгод\b", text):
        # Иногда годовой пишут как «2024, 12 месяцев»
        return ParsedPeriod("annual", year, None, str(year), 0)

    return None


def pdf_filename(ticker: str, parsed: ParsedPeriod) -> str:
    return f"{ticker.upper()}_{parsed.period_key}.pdf"


def filter_coverage_entries(
    entries: list,
    *,
    min_annual_year: int = 2010,
) -> list:
    """
    Все годовые с year >= min_annual_year + один самый свежий interim.
    `entries` — объекты с атрибутами period_type, fiscal_year, interim_rank
    (или ParsedPeriod / ReportEntry).
    """
    annuals = [
        e
        for e in entries
        if getattr(e, "period_type", None) == "annual"
        and int(getattr(e, "fiscal_year", getattr(e, "year", 0))) >= min_annual_year
    ]
    interims = [e for e in entries if getattr(e, "period_type", None) != "annual"]
    latest = None
    if interims:
        latest = max(
            interims,
            key=lambda e: (
                int(getattr(e, "fiscal_year", getattr(e, "year", 0))),
                int(getattr(e, "interim_rank", 0)),
            ),
        )
    out = list(annuals)
    if latest is not None:
        out.append(latest)
    return out
