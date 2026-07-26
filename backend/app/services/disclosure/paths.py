"""Пути PDF на диске: TICKER_YYYY.pdf / TICKER_YYYY_Q1.pdf / TICKER_YYYY_H1.pdf."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from app.config import settings


def reports_root() -> Path:
    return Path(settings.MASS_PARSE_REPORTS_DIR).expanduser().resolve()


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


def pdf_path_for(
    ticker: str,
    period_type: str,
    fiscal_year: int,
    fiscal_quarter: Optional[int] = None,
) -> Path:
    key = period_key(period_type, fiscal_year, fiscal_quarter)
    return reports_root() / ticker.upper() / f"{ticker.upper()}_{key}.pdf"


def interim_rank(period_type: str, fiscal_quarter: Optional[int]) -> int:
    if period_type == "annual":
        return 0
    if period_type == "quarterly" and fiscal_quarter == 1:
        return 1
    if period_type == "semi_annual":
        return 2
    if period_type == "quarterly" and fiscal_quarter == 3:
        return 3
    return 0
