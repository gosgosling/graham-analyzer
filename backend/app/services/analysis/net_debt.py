"""Чистый долг (Net Debt) = Долг − Наличность, млн валюты отчёта."""
from typing import Optional


def compute_net_debt(
    debt: Optional[float],
    cash_and_equivalents: Optional[float],
) -> Optional[float]:
    if debt is None or cash_and_equivalents is None:
        return None
    return round(float(debt) - float(cash_and_equivalents), 3)
