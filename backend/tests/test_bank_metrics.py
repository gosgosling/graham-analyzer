"""Банковские показатели: риск, качество активов, фондирование, капитал.

Цифры в примерах — порядка величин Сбера за 2024 год, чтобы при ручном
разборе отчёта было с чем сверяться глазами.
"""
from types import SimpleNamespace

import pytest

from app.services.analysis.bank_metrics import (
    compute_bank_metrics,
    evaluate_all,
    evaluate_bank_metric,
)


def _bank(**overrides) -> SimpleNamespace:
    """Банк-заглушка: суммы в млн ₽, расходные величины — положительные."""
    base = {
        "net_income": 1_580_000.0,
        "total_assets": 57_000_000.0,
        "equity": 7_000_000.0,
        "net_interest_income": 2_900_000.0,
        "interest_expense": 3_100_000.0,
        "provisions": 280_000.0,
        "gross_loans": 43_000_000.0,
        "loan_loss_allowance": 1_500_000.0,
        "npl_loans": 1_600_000.0,
        "customer_deposits": 40_000_000.0,
        "risk_weighted_assets": 50_000_000.0,
        "capital_adequacy_ratio": 13.3,
        "capital_adequacy_core": 11.2,
        "loans_retail": 17_000_000.0,
        "loans_corporate": 26_000_000.0,
        "deposits_retail": 25_000_000.0,
        "deposits_corporate": 15_000_000.0,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


# ─── Расчёт ──────────────────────────────────────────────────────────────────


def test_core_ratios():
    m = compute_bank_metrics(_bank())

    assert m.roa == pytest.approx(2.77, abs=0.01)              # 1.58 / 57 трлн
    assert m.net_interest_margin == pytest.approx(5.09, abs=0.01)
    assert m.cost_of_risk == pytest.approx(0.65, abs=0.01)     # резерв 280 / портфель 43 000
    assert m.npl_ratio == pytest.approx(3.72, abs=0.01)
    assert m.npl_coverage == pytest.approx(93.75, abs=0.01)    # резерв 1500 / NPL 1600


def test_net_loans_are_gross_minus_allowance():
    """Баланс показывает кредиты за вычетом резерва — восстанавливаем ту же величину."""
    m = compute_bank_metrics(_bank())

    assert m.net_loans == pytest.approx(41_500_000.0)
    # LDR считается по чистым кредитам: именно они профинансированы депозитами
    assert m.loans_to_deposits == pytest.approx(103.75, abs=0.01)


def test_capital_ratio_is_taken_as_disclosed_and_cross_checked():
    """Н1.0 берём как раскрыл эмитент, а капитал/RWA — сверка ручного ввода."""
    m = compute_bank_metrics(_bank())

    assert m.capital_adequacy_ratio == 13.3
    assert m.capital_to_rwa == pytest.approx(14.0, abs=0.01)


def test_missing_denominator_gives_none_not_zero():
    """Пустой портфель — «не посчитать», а не «стоимость риска ноль»."""
    m = compute_bank_metrics(_bank(gross_loans=None, customer_deposits=0))

    assert m.cost_of_risk is None
    assert m.npl_ratio is None
    assert m.loans_to_deposits is None
    assert m.roa is not None  # остальное считается по-прежнему


def test_allowance_absent_means_net_equals_gross():
    """Если резерв не выписан из примечания — портфель остаётся валовым."""
    m = compute_bank_metrics(_bank(loan_loss_allowance=None))

    assert m.net_loans == pytest.approx(43_000_000.0)
    assert m.npl_coverage is None


# ─── Светофор ────────────────────────────────────────────────────────────────


def test_lower_is_better_metrics_are_not_inverted():
    """Стоимость риска и NPL: чем меньше, тем лучше — типичная ошибка порогов."""
    assert evaluate_bank_metric("cost_of_risk", 0.8) == "good"
    assert evaluate_bank_metric("cost_of_risk", 1.7) == "normal"
    assert evaluate_bank_metric("cost_of_risk", 3.0) == "bad"

    assert evaluate_bank_metric("npl_ratio", 3.0) == "good"
    assert evaluate_bank_metric("npl_ratio", 9.0) == "bad"


def test_higher_is_better_metrics():
    assert evaluate_bank_metric("roa", 2.5) == "good"
    assert evaluate_bank_metric("roa", 1.2) == "normal"
    assert evaluate_bank_metric("roa", 0.4) == "bad"

    assert evaluate_bank_metric("npl_coverage", 120.0) == "good"
    assert evaluate_bank_metric("capital_adequacy_ratio", 9.0) == "bad"


def test_informational_metrics_have_no_traffic_light():
    """У стоимости фондирования нет «хорошего» уровня в отрыве от ставки ЦБ."""
    assert evaluate_bank_metric("cost_of_funding", 7.5) == "n/a"
    assert evaluate_bank_metric("capital_to_rwa", 14.0) == "n/a"


def test_missing_value_is_not_bad():
    """Незаполненное поле не должно краснеть: это пробел в данных, а не риск."""
    assert evaluate_bank_metric("cost_of_risk", None) == "n/a"
    assert evaluate_bank_metric("roa", None) == "n/a"


def test_evaluate_all_covers_every_metric():
    statuses = evaluate_all(compute_bank_metrics(_bank()))

    assert statuses["cost_of_risk"] == "good"
    assert statuses["npl_ratio"] == "good"
    assert statuses["npl_coverage"] == "normal"      # 93.75% < 100%
    assert statuses["loans_to_deposits"] == "normal"  # 103.75% > 100%
    assert statuses["capital_adequacy_ratio"] == "good"


# ─── Разбивка на розницу и корпоратив, основной капитал ──────────────────────


def test_retail_shares_show_profile_not_quality():
    """Доля розницы — профиль банка, а не оценка: светофора у неё нет."""
    m = compute_bank_metrics(_bank())

    assert m.retail_loans_share == pytest.approx(39.53, abs=0.01)
    assert m.retail_deposits_share == pytest.approx(62.5, abs=0.01)
    assert evaluate_bank_metric("retail_loans_share", m.retail_loans_share) == "n/a"


def test_core_capital_is_stricter_than_total():
    """Н1.1 поглощает убытки первым, поэтому и порог у него отдельный."""
    assert evaluate_bank_metric("capital_adequacy_core", 11.2) == "good"
    assert evaluate_bank_metric("capital_adequacy_core", 9.0) == "normal"
    assert evaluate_bank_metric("capital_adequacy_core", 7.0) == "bad"
    # тот же уровень по общему нормативу — уже не «хорошо»
    assert evaluate_bank_metric("capital_adequacy_ratio", 11.2) == "normal"


def test_core_capital_is_taken_as_disclosed():
    assert compute_bank_metrics(_bank()).capital_adequacy_core == 11.2
    assert compute_bank_metrics(_bank(capital_adequacy_core=None)).capital_adequacy_core is None


# ─── Спред к ключевой ставке ────────────────────────────────────────────────


def test_funding_spread_needs_the_rate_of_the_same_period():
    """Стоимость фондирования сравнивается со ставкой ТОГО ЖЕ года.

    12% годовых при ключевой 4% и при 19% означают противоположные вещи,
    поэтому без ставки периода спред не считается вовсе.
    """
    bank = _bank(interest_expense=5_933_800, customer_deposits=49_373_500)

    assert compute_bank_metrics(bank).funding_spread is None
    assert compute_bank_metrics(bank, key_rate=19.13).funding_spread == pytest.approx(-7.11, abs=0.01)


def test_cheap_funding_is_an_advantage_not_a_problem():
    """Ниже ключевой — преимущество: знак минус должен красить в зелёный."""
    assert evaluate_bank_metric("funding_spread", -7.11) == "good"   # Сбер 2025
    assert evaluate_bank_metric("funding_spread", -1.5) == "normal"
    assert evaluate_bank_metric("funding_spread", 2.0) == "bad"      # дороже рынка


def test_key_rate_itself_has_no_verdict():
    """Ключевая ставка — контекст, а не оценка банка."""
    assert evaluate_bank_metric("key_rate", 19.13) == "n/a"


# ─── Приведение промежуточных отчётов к году ────────────────────────────────


def _half_year(**overrides) -> SimpleNamespace:
    """Полугодие того же банка: потоки вдвое меньше, баланс тот же."""
    return _bank(
        period_type="semi_annual",
        fiscal_quarter=None,
        net_income=790_000.0,
        net_interest_income=1_450_000.0,
        interest_expense=1_550_000.0,
        provisions=140_000.0,
        **overrides,
    )


def test_interim_flow_metrics_are_annualised():
    """Полугодие с половинными потоками даёт те же годовые показатели.

    Иначе банк, опубликовавший отчёт за 6 месяцев, выглядел бы вдвое хуже
    себя самого: в числителе половина года, в знаменателе полный баланс.
    """
    year = compute_bank_metrics(_bank(period_type="annual"))
    half = compute_bank_metrics(_half_year())

    assert half.roa == pytest.approx(year.roa, abs=0.01)
    assert half.net_interest_margin == pytest.approx(year.net_interest_margin, abs=0.01)
    assert half.cost_of_risk == pytest.approx(year.cost_of_risk, abs=0.01)
    assert half.cost_of_funding == pytest.approx(year.cost_of_funding, abs=0.01)


def test_balance_ratios_are_not_annualised():
    """Доли и покрытия — отношения балансовых величин, множителю там не место."""
    year = compute_bank_metrics(_bank(period_type="annual"))
    half = compute_bank_metrics(_half_year())

    assert half.npl_ratio == year.npl_ratio
    assert half.npl_coverage == year.npl_coverage
    assert half.loans_to_deposits == year.loans_to_deposits
    assert half.retail_loans_share == year.retail_loans_share
    assert half.retail_deposits_share == year.retail_deposits_share
    assert half.capital_to_rwa == year.capital_to_rwa


def test_nine_months_report_is_annualised_by_four_thirds():
    """Квартальные отчёты накопительные: Q3 — это девять месяцев, не три."""
    nine = compute_bank_metrics(
        _bank(period_type="quarterly", fiscal_quarter=3, net_income=1_185_000.0)
    )

    # 1 185 000 × 12/9 = 1 580 000 — годовая прибыль из примера
    assert nine.roa == pytest.approx(compute_bank_metrics(_bank()).roa, abs=0.01)


def test_report_without_period_is_treated_as_full_year():
    """Заглушка без типа периода не должна множиться на случайный коэффициент."""
    assert compute_bank_metrics(_bank()).roa == pytest.approx(2.77, abs=0.01)


# ─── LTM вместо приведения к году ───────────────────────────────────────────


def test_ltm_flows_win_over_annualisation():
    """Фактические 12 месяцев важнее удвоенного полугодия.

    Первое полугодие может быть сильнее второго — тогда удвоение завышает
    отдачу. Если LTM собран, экстраполировать нечего.
    """
    metrics = compute_bank_metrics(
        _half_year(),
        ltm_flows={
            "net_income": 1_400_000.0,      # не 790 × 2 = 1 580 000
            "net_interest_income": 2_700_000.0,
            "provisions": 300_000.0,
            "interest_expense": 3_000_000.0,
        },
    )

    assert metrics.flow_basis == "ltm"
    assert metrics.roa == pytest.approx(1_400_000 / 57_000_000 * 100, abs=0.01)
    assert metrics.cost_of_risk == pytest.approx(300_000 / 43_000_000 * 100, abs=0.01)


def test_missing_ltm_flow_falls_back_to_annualisation():
    """Пустое LTM-поле не обнуляет показатель, а откатывает его к удвоению."""
    metrics = compute_bank_metrics(
        _half_year(),
        ltm_flows={"net_income": 1_400_000.0, "provisions": None},
    )

    assert metrics.cost_of_risk == compute_bank_metrics(_half_year()).cost_of_risk


def test_flow_basis_names_the_source():
    assert compute_bank_metrics(_bank(period_type="annual")).flow_basis == "reported"
    assert compute_bank_metrics(_half_year()).flow_basis == "annualised"


def test_flow_basis_is_not_a_metric_with_a_verdict():
    """Служебной пометке не место в светофоре."""
    assert "flow_basis" not in evaluate_all(compute_bank_metrics(_bank()))
