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
    debt_principal: Optional[float] = None,  # noqa: ARG001 — reserved, не в формуле
) -> Optional[float]:
    """
    FCF = OCF − CAPEX − аренда (тело + проценты).

    CAPEX — приобретение ОС + НМА (положительный отток).
    Аренда: если в ОДДС одна строка «Выплаты обязательств по аренде» —
    вся сумма в lease_principal, lease_interest = null.

    debt_principal (погашение кредитов/облигаций) в формулу НЕ входит:
    это финансирование, не sustenance capex/lease. Параметр оставлен для
    совместимости вызовов и особых ручных кейсов — игнорируется.
    """
    if operating_cash_flow is None or capex is None:
        return None
    total_out = (
        float(capex)
        + _outflow(lease_principal)
        + _outflow(lease_interest)
    )
    return round(float(operating_cash_flow) - total_out, 3)
