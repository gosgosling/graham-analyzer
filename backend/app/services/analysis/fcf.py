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
    interest_paid: Optional[float] = None,
    debt_principal: Optional[float] = None,  # noqa: ARG001 — не в формуле
) -> Optional[float]:
    """
    FCF = OCF − CAPEX − аренда − проценты уплаченные (из financing).

    CAPEX — ОС + НМА (положительный отток).
    Аренда: одна строка «выплаты по аренде» → вся сумма в lease_principal.
    interest_paid — строка «Проценты уплаченные» из ФИНАНСОВОЙ деятельности
    (когда в операционной проценты добавлены обратно). Если проценты уже
    внутри OCF — поле должно быть null, иначе будет двойной вычет.

    debt_principal (погашение кредитов/облигаций) в формулу НЕ входит.
    """
    if operating_cash_flow is None or capex is None:
        return None
    total_out = (
        float(capex)
        + _outflow(lease_principal)
        + _outflow(lease_interest)
        + _outflow(interest_paid)
    )
    return round(float(operating_cash_flow) - total_out, 3)
