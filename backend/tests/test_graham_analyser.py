"""Классификация компании: вердикт собирается только из применимых метрик."""
from app.services.analysis.graham_analyser import classify_company


def _industrial(**kw) -> dict:
    """Мультипликаторы недооценённой промышленной компании по Грэму."""
    base = {
        "pe_ratio": 8.0,
        "pb_ratio": 1.2,
        "roe": 18.0,
        "debt_to_equity": 0.4,
        "current_ratio": 2.2,
        "dividend_yield": 8.0,
        "cost_to_income": None,
    }
    base.update(kw)
    return base


def test_all_good_gives_undervalued():
    assert classify_company(_industrial())["classify"] == "undervalued"


def test_single_bad_metric_gives_overvalued():
    """Один красный флаг перебивает остальные зелёные — так и задумано."""
    assert classify_company(_industrial(pe_ratio=40.0))["classify"] == "overvalued"


def test_mixed_metrics_give_stable():
    result = classify_company(_industrial(pe_ratio=20.0, dividend_yield=4.0))

    assert result["pe_ratio_status"] == "normal"
    assert result["classify"] == "stable"


def test_no_data_is_not_a_buy_signal():
    """Пустые мультипликаторы не должны выглядеть как недооценка."""
    empty = {k: None for k in _industrial()}
    assert classify_company(empty)["classify"] == "overvalued"


def test_sector_thresholds_change_the_verdict():
    """P/E 12 и P/B 1.3: дешёво для промышленности, дороговато для банка."""
    mult = _industrial(pe_ratio=12.0, pb_ratio=1.3, debt_to_equity=None, current_ratio=None)

    industrial = classify_company(mult, sector="machinery")
    bank = classify_company(mult, report_type="bank", sector="banks")

    assert industrial["profile_key"] == "industrial"
    assert bank["profile_key"] == "bank"
    assert industrial["classify"] == "undervalued"
    assert bank["classify"] == "stable"


def test_bank_leverage_is_ignored_in_verdict():
    """D/E 8 и Current Ratio 0.3 у банка — норма, вердикт из-за них не портится."""
    result = classify_company(
        _industrial(
            pe_ratio=7.0, pb_ratio=0.9, debt_to_equity=8.0,
            current_ratio=0.3, cost_to_income=35.0,
        ),
        report_type="bank",
    )

    assert result["debt_status"] == "n/a"
    assert result["liquidity_status"] == "n/a"
    assert result["cir_status"] == "good"
    assert result["classify"] == "undervalued"


def test_bank_cost_to_income_can_spoil_the_verdict():
    """Дешёвый банк с раздутыми расходами — не покупка."""
    result = classify_company(
        _industrial(
            pe_ratio=7.0, pb_ratio=0.9, debt_to_equity=8.0,
            current_ratio=0.3, cost_to_income=70.0,
        ),
        report_type="bank",
    )

    assert result["cir_status"] == "bad"
    assert result["classify"] == "overvalued"


def test_cost_to_income_ignored_for_non_bank():
    """CIR считается только для банков — у промышленной компании он не смысловой."""
    result = classify_company(_industrial(cost_to_income=90.0))

    assert result["cir_status"] == "n/a"
    assert result["classify"] == "undervalued"


def test_manual_profile_override_is_respected():
    result = classify_company(_industrial(), sector="consumer", profile_key="retail_grocery")

    assert result["profile_key"] == "retail_grocery"
    assert result["profile_label"]
