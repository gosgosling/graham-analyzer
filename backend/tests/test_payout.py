"""Доля прибыли, выплаченная дивидендами.

Грэм требовал не просто дивидендов, а обеспеченных: выплата сверх
заработанного финансируется долгом и рано или поздно прекращается.
"""
from types import SimpleNamespace

import pytest

from app.services.analysis.payout import compute_dividend_payout, evaluate_payout


def _report(**overrides) -> SimpleNamespace:
    """Дивиденд — в рублях на акцию, прибыль — в млн, акции — в штуках."""
    base = {
        "dividends_paid": True,
        "dividends_per_share": 34.84,
        "net_income": 1_580_000.0,       # млн ₽
        "shares_outstanding": 21_586_948_000,
        "shares_issued": None,
        "shares_weighted_avg": None,
        "treasury_shares": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_payout_matches_manual_calculation():
    """34,84 ₽ × 21,59 млрд акций = 752 млрд ₽ на 1 580 млрд прибыли."""
    assert compute_dividend_payout(_report()) == pytest.approx(47.6, abs=0.1)


def test_units_are_not_mixed_up():
    """Дивиденд в полных рублях, прибыль в миллионах — цена ошибки здесь ×10⁶."""
    payout = compute_dividend_payout(
        _report(dividends_per_share=10.0, shares_outstanding=1_000_000_000, net_income=20_000.0)
    )

    # 10 ₽ × 1 млрд = 10 млрд ₽ = 10 000 млн при прибыли 20 000 млн → ровно половина
    assert payout == pytest.approx(50.0)


def test_no_dividends_means_no_ratio():
    """Отсутствие выплаты — не нулевой payout, а отсутствие показателя."""
    assert compute_dividend_payout(_report(dividends_paid=False)) is None


def test_loss_year_gives_none_not_negative():
    """Payout от убытка — бессмысленное число, которое выглядит как расчёт."""
    assert compute_dividend_payout(_report(net_income=-500_000.0)) is None
    assert compute_dividend_payout(_report(net_income=0.0)) is None


def test_missing_shares_or_profit_gives_none():
    assert compute_dividend_payout(_report(shares_outstanding=None)) is None
    assert compute_dividend_payout(_report(net_income=None)) is None


def test_shares_follow_capitalisation_rule():
    """Акции берутся те же, что и для капитализации: размещённые минус казначейские."""
    payout = compute_dividend_payout(
        _report(
            shares_outstanding=None,
            shares_issued=1_000_000_000,
            treasury_shares=200_000_000,
            dividends_per_share=10.0,
            net_income=16_000.0,
        )
    )

    # 10 ₽ × 800 млн = 8 000 млн при прибыли 16 000 млн
    assert payout == pytest.approx(50.0)


def test_traffic_light_flags_payout_above_profit():
    assert evaluate_payout(45.0) == "good"
    assert evaluate_payout(85.0) == "normal"
    assert evaluate_payout(140.0) == "bad"   # платят больше, чем заработали
    assert evaluate_payout(None) == "n/a"
