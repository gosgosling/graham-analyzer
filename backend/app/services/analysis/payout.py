"""Доля прибыли, выплаченная дивидендами (payout ratio).

Грэм требовал не просто дивидендов, а непрерывных и обеспеченных: выплата
сверх заработанного финансируется долгом или продажей активов и рано или
поздно прекращается. Payout показывает именно это — сколько процентов
прибыли ушло акционерам.

Показатель не банковский: он применим ко всем компаниям и живёт отдельно от
`bank_metrics`. Для банка у него есть дополнительный смысл — щедрая выплата
при тонком капитале ограничена нормативами ЦБ раньше, чем желанием
менеджмента.

Считается по одному отчёту: дивиденд на акцию × количество акций ÷ прибыль.
Акции берутся те же, что и для капитализации, поэтому у компаний с двумя
классами (Сбер, Татнефть) значение относится к своему тикеру.
"""
from typing import Any, Optional

from app.services.analysis.share_counts import resolve_shares_for_multipliers

Status = str  # 'good' | 'normal' | 'bad' | 'n/a'

# Порог «нормально» — вся прибыль; выше 100% выплата уже не из заработанного.
# Порог «хорошо» — до 70%: остаётся запас на развитие и на плохой год.
_GOOD_PCT = 70.0
_NORMAL_PCT = 100.0

PAYOUT_HINT = "≤ 70% — выплата с запасом; > 100% — платят не из прибыли"


def _num(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def compute_dividend_payout(report: Any) -> Optional[float]:
    """Доля прибыли, выплаченная дивидендами, %.

    Returns:
        None, если дивидендов не было, неизвестны акции или прибыль, а также
        при убытке: payout от отрицательной прибыли — бессмысленное число,
        которое в таблице выглядит как аккуратный минус вместо предупреждения.
    """
    if not getattr(report, "dividends_paid", False):
        return None

    dps = _num(getattr(report, "dividends_per_share", None))
    net_income_mln = _num(getattr(report, "net_income", None))
    shares = resolve_shares_for_multipliers(report)

    if dps is None or shares is None or net_income_mln is None:
        return None
    if net_income_mln <= 0:
        return None

    # Дивиденд — в полных единицах валюты, прибыль — в миллионах.
    total_dividends_mln = dps * shares / 1_000_000
    return round(total_dividends_mln / net_income_mln * 100, 2)


def evaluate_payout(value: Optional[float]) -> Status:
    """Светофор: до 70% — хорошо, до 100% — нормально, выше — тревога."""
    if value is None:
        return "n/a"
    if value <= _GOOD_PCT:
        return "good"
    return "normal" if value <= _NORMAL_PCT else "bad"
