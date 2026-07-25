"""Свободный денежный поток, чистый долг и выбор количества акций."""
from types import SimpleNamespace

from app.services.analysis.fcf import compute_fcf
from app.services.analysis.net_debt import compute_net_debt
from app.services.analysis.share_counts import (
    compute_circulation_shares,
    explain_shares_cap_basis,
    resolve_shares_for_multipliers,
)


# ─── FCF ────────────────────────────────────────────────────────────────────


def test_fcf_base_formula():
    assert compute_fcf(15_000, 5_000) == 10_000.0


def test_fcf_subtracts_capex_and_lease_only():
    """FCF = OCF − CAPEX − аренда; погашение кредитов (debt_principal) игнорируется."""
    assert compute_fcf(15_000, 5_000, 2_000, 500, 1_500) == 7_500.0
    assert compute_fcf(15_000, 5_000, 2_000, 500, None) == 7_500.0


def test_fcf_combined_lease_line_without_interest():
    """Одна строка «выплаты по аренде» → только lease_principal."""
    # MVID-like: OCF=-392, CAPEX=8804 (ОС+НМА), lease=11882
    assert compute_fcf(-392, 8_804, 11_882, None, 133_196) == -21_078.0


def test_fcf_treats_missing_outflows_as_zero():
    assert compute_fcf(15_000, 5_000, None, None, None) == 10_000.0


def test_fcf_requires_ocf_and_capex():
    assert compute_fcf(None, 5_000) is None
    assert compute_fcf(15_000, None) is None


def test_fcf_can_be_negative():
    assert compute_fcf(3_000, 8_000) == -5_000.0


# ─── Чистый долг ────────────────────────────────────────────────────────────


def test_net_debt_subtracts_cash():
    assert compute_net_debt(20_000, 5_000) == 15_000.0


def test_net_debt_can_be_negative_for_cash_rich_company():
    assert compute_net_debt(1_000, 9_000) == -8_000.0


# ─── Количество акций ───────────────────────────────────────────────────────


def _shares(**kw) -> SimpleNamespace:
    base = {
        "shares_outstanding": None,
        "shares_issued": None,
        "shares_weighted_avg": None,
        "treasury_shares": None,
    }
    base.update(kw)
    return SimpleNamespace(**base)


def test_circulation_prefers_explicit_outstanding():
    src = _shares(shares_outstanding=900, shares_issued=1_000, treasury_shares=50)
    assert compute_circulation_shares(
        src.shares_outstanding, src.shares_issued, src.treasury_shares
    ) == 900


def test_circulation_derived_from_issued_minus_treasury():
    assert compute_circulation_shares(None, 1_000, 150) == 850


def test_circulation_needs_treasury_to_derive():
    """Без казначейских акций «размещённые» — это не акции в обращении."""
    assert compute_circulation_shares(None, 1_000, None) is None


def test_shares_priority_falls_back_to_weighted_then_issued():
    assert resolve_shares_for_multipliers(_shares(shares_outstanding=900)) == 900
    assert resolve_shares_for_multipliers(
        _shares(shares_weighted_avg=800, shares_issued=1_000)
    ) == 800
    assert resolve_shares_for_multipliers(_shares(shares_issued=1_000)) == 1_000
    assert resolve_shares_for_multipliers(_shares()) is None


def test_explain_shares_mentions_circulation_basis():
    src = _shares(shares_outstanding=900)
    text = explain_shares_cap_basis(src, 900)

    assert text is not None
    assert "в обращении" in text


def test_explain_shares_mentions_weighted_when_used():
    src = _shares(shares_weighted_avg=800)
    text = explain_shares_cap_basis(src, 800)

    assert text is not None
    assert "средневзвешенное" in text.lower()


def test_net_debt_none_when_either_side_missing():
    assert compute_net_debt(None, 5_000) is None
    assert compute_net_debt(20_000, None) is None
