from app.routers.screen_router import thresholds


def _rule(data, standard, metric):
    std = next(s for s in data["standards"] if s["key"] == standard)
    return next(r for r in std["rules"] if r["metric"] == metric)


def test_industrial_profile_keeps_book_numbers():
    data = thresholds()
    assert data["base_profile"] == "industrial"
    cell = _rule(data, "defensive", "current_ratio")["applied"]["industrial"]
    assert cell == {"text": "≥ 2", "status": "same"}


def test_sector_shifts_threshold_relative_to_industrial():
    data = thresholds()
    # Нефтегаз: «хорошо» 1 против 2 у промышленности — порог вдвое мягче в обоих сводах.
    assert _rule(data, "defensive", "current_ratio")["applied"]["oil_gas_mining"]["text"] == "≥ 1"
    assert _rule(data, "enterprising", "current_ratio")["applied"]["oil_gas_mining"]["text"] == "≥ 0.75"
    assert _rule(data, "defensive", "pe_average")["applied"]["oil_gas_mining"]["status"] == "shifted"


def test_bank_rules_only_for_banks_and_liquidity_not_measured():
    data = thresholds()
    npl = _rule(data, "defensive", "npl_ratio")["applied"]
    assert npl["bank"]["status"] != "out"
    assert npl["industrial"]["status"] == "out"
    assert _rule(data, "defensive", "current_ratio")["applied"]["bank"]["status"] == "na"
    assert _rule(data, "defensive", "cash_growth")["applied"]["bank"]["status"] == "out"
