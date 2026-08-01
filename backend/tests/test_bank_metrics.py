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
