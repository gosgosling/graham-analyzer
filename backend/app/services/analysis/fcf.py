"""Расчёт FCF из компонентов денежного потока (млн валюты отчёта)."""

from typing import Optional


def _outflow(val: Optional[float]) -> float:
    """Опциональный отток: None → 0."""
    if val is None:
        return 0.0
    return float(val)


def compute_fcf(
    operating_cash_flow: Optional[float],
    capex: Optional[float],
    lease_principal: Optional[float] = None,
    lease_interest: Optional[float] = None,
    debt_principal: Optional[float] = None,
) -> Optional[float]:
    """
    FCF = OCF − CAPEX − тело аренды − проценты по аренде − тело долга (долг. ЦБ).

    OCF и CAPEX обязательны для расчёта (базовая формула).
    Остальные слагаемые опциональны (отсутствие = 0).
    Все оттоки хранятся как положительные числа.
    """
    if operating_cash_flow is None or capex is None:
        return None
    total_out = (
        float(capex)
        + _outflow(lease_principal)
        + _outflow(lease_interest)
        + _outflow(debt_principal)
    )
    return round(float(operating_cash_flow) - total_out, 3)
