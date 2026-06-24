"""Определение типа акций по тикеру MOEX (обыкновенные vs привилегированные)."""
from __future__ import annotations

from typing import Optional

# Обыкновенные тикеры, которые оканчиваются на «P», но НЕ являются префами.
_ORDINARY_TICKERS_ENDING_IN_P = frozenset({"GAZP"})


def detect_preferred_share(
    ticker: Optional[str],
    name: Optional[str] = None,
) -> bool:
    """Эвристика: инструмент — привилегированные акции на MOEX.

    Префы: отдельный тикер с суффиксом P (SBERP, TRNFP, BANEP …), обычно ≥5
    символов. Исключение: GAZP — обыкновенные акции Газпрома.
    """
    if name and "привилегирован" in name.lower():
        return True
    if not ticker:
        return False
    t = ticker.strip().upper()
    if t in _ORDINARY_TICKERS_ENDING_IN_P:
        return False
    return len(t) >= 5 and t.endswith("P")


def instrument_can_be_preferred(
    ticker: Optional[str],
    name: Optional[str] = None,
) -> bool:
    """Тикер/название допускают режим «привилегированные акции»."""
    return detect_preferred_share(ticker, name)
