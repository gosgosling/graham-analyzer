"""Расчёт FCF из компонентов денежного потока (млн валюты отчёта).

Отдельно — очистка потока гибрида от встроенного банка: у Яндекса и биржи
в операционном потоке сидит прирост клиентских депозитов и выдача кредитов.
Это движение чужих денег, а не заработок ядра, и без вычета свободный поток
выглядит вдвое больше, чем есть.
"""

from typing import Optional, Tuple


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


def compute_banking_flow(
    current: Optional[object],
    previous: Optional[object] = None,
) -> Tuple[Optional[float], Optional[str]]:
    """Приток денег от встроенного финсервиса за период, млн.

    Два источника, в порядке надёжности:

    1. **Строки ОДДС** (`cf_customer_deposits`, `cf_customer_loans`) — как
       напечатано в отчёте, со знаком. Это фактическое движение денег.
    2. **Разница балансовых остатков** — запасной вариант, когда строки ОДДС
       не выписаны. Он завышает приток: в остатки попадают секьюритизация,
       списания и прекращение признания активов, которые баланс меняют, а
       денежный поток — нет. У Яндекса за 2025 год это 100 млрд против 77.

    Модель общая для любой компании со встроенным финсервисом: Яндекс Банк,
    Озон Банк и подобные — названия строк в ОДДС у них совпадают по смыслу.

    Returns:
        (приток, основание) — основание 'cash_flow' | 'balance_delta' | None,
        чтобы интерфейс мог честно назвать, откуда взята цифра.
    """
    if current is None:
        return None, None

    def field(obj, name: str) -> Optional[float]:
        value = getattr(obj, name, None)
        return None if value is None else float(value)

    # 1. Прямые строки ОДДС
    deposits_cf = field(current, "cf_customer_deposits")
    loans_cf = field(current, "cf_customer_loans")
    if deposits_cf is not None or loans_cf is not None:
        return round((deposits_cf or 0.0) + (loans_cf or 0.0), 3), "cash_flow"

    # 2. Запасной вариант — приросты остатков
    if previous is None:
        return None, None

    deposits_now, deposits_prev = field(current, "customer_deposits"), field(previous, "customer_deposits")
    loans_now, loans_prev = field(current, "gross_loans"), field(previous, "gross_loans")
    if deposits_now is None or deposits_prev is None:
        return None, None

    loans_growth = 0.0
    if loans_now is not None and loans_prev is not None:
        loans_growth = loans_now - loans_prev

    return round((deposits_now - deposits_prev) - loans_growth, 3), "balance_delta"


def compute_core_fcf(
    reported_fcf: Optional[float],
    banking_flow: Optional[float],
) -> Optional[float]:
    """FCF ядра: свободный поток за вычетом притока от банковского баланса.

    Именно эта величина сопоставима с дивидендами: платить из прироста
    клиентских депозитов — значит финансировать выплату чужими деньгами.
    """
    if reported_fcf is None or banking_flow is None:
        return None
    return round(float(reported_fcf) - float(banking_flow), 3)
