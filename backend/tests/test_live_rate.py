"""Живая безрисковая ставка: средняя доходность ОФЗ за месяц вместо ручной."""

from datetime import date
from types import SimpleNamespace

from app.services.market.ofz_service import LiveAssumption, LiveRate

BASE = SimpleNamespace(
    year=2026, risk_free_rate=16.0, risk_premium=5.0, dividend_growth=6.59,
    payout=None, long_run_growth=9.0, normalized_risk_free_rate=10.0, note="", source="manual",
)


def test_ставка_берётся_из_кривой_остальное_из_допущений():
    live = LiveAssumption(BASE, LiveRate(16.44, 22, date(2026, 9, 2), date(2026, 10, 1)))
    assert live.risk_free_rate == 16.44
    assert live.manual_risk_free_rate == 16.0
    # Премия и потолок роста — суждения, их кривая не подсказывает.
    assert live.risk_premium == 5.0
    assert live.long_run_growth == 9.0
    assert live.risk_free_source == "ОФЗ 10 лет, средняя за месяц"
    assert "22 торговых дня" in live.risk_free_note


def test_без_кривой_остаётся_ручная_ставка():
    live = LiveAssumption(BASE, None)
    assert live.risk_free_rate == 16.0
    assert live.risk_free_source == "допущения"


def test_подпись_согласует_число_дней():
    assert "21 торговый день" in LiveRate(16.0, 21, date(2026, 9, 2), date(2026, 10, 1)).label
    assert "5 торговых дней" in LiveRate(16.0, 5, date(2026, 9, 2), date(2026, 10, 1)).label
