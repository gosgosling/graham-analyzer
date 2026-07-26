"""Эвристический календарь ожиданий промежуточной/годовой отчётности (РФ)."""
from __future__ import annotations

from datetime import date
from typing import Optional


def expected_periods_for_today(today: Optional[date] = None) -> list[dict]:
    """
    Периоды, которые «пора ждать» на текущую дату.

    Возвращает list of {
      period_type, fiscal_year, fiscal_quarter, expectation_start: date
    }
    """
    today = today or date.today()
    y = today.year
    out: list[dict] = []

    # Annual Y-1 — с 1 апреля года Y
    out.append(
        {
            "period_type": "annual",
            "fiscal_year": y - 1,
            "fiscal_quarter": None,
            "expectation_start": date(y, 4, 1),
        }
    )
    # Если уже после НГ — также annual Y-2 как «должен быть давно» (для overdue)
    out.append(
        {
            "period_type": "annual",
            "fiscal_year": y - 2,
            "fiscal_quarter": None,
            "expectation_start": date(y - 1, 4, 1),
        }
    )

    # Q1 года Y — с 1 мая
    out.append(
        {
            "period_type": "quarterly",
            "fiscal_year": y,
            "fiscal_quarter": 1,
            "expectation_start": date(y, 5, 1),
        }
    )
    # H1 года Y — с 1 августа
    out.append(
        {
            "period_type": "semi_annual",
            "fiscal_year": y,
            "fiscal_quarter": None,
            "expectation_start": date(y, 8, 1),
        }
    )
    # Q3/9M года Y — с 1 ноября
    out.append(
        {
            "period_type": "quarterly",
            "fiscal_year": y,
            "fiscal_quarter": 3,
            "expectation_start": date(y, 11, 1),
        }
    )

    # Если янв–март — ещё актуален Q3 прошлого года и H1 прошлого
    if today.month <= 3:
        out.append(
            {
                "period_type": "quarterly",
                "fiscal_year": y - 1,
                "fiscal_quarter": 3,
                "expectation_start": date(y - 1, 11, 1),
            }
        )

    return out


def compute_coverage_status(
    *,
    in_db: bool,
    on_edisclosure: bool,
    expectation: str,
    expectation_start: Optional[date],
    today: Optional[date] = None,
) -> str:
    """waiting | overdue | available | in_service | unknown"""
    today = today or date.today()
    if in_db:
        return "in_service"
    if on_edisclosure:
        return "available"
    if expectation == "expected" and expectation_start and today >= expectation_start:
        return "overdue"
    if expectation == "expected":
        return "waiting"
    return "unknown"
