"""Оценка компании: множитель по своим числам, поправка на активы, полоса.

Опорный пример поправки на активы — гл. 34, с. 634.
"""

import pytest

from app.services.analysis.company_valuation import (
    ASSET_WEIGHT,
    PENALTY_COVERAGE_FRAGILE,
    PENALTY_HISTORY_THIN,
    PENALTY_SPREAD_WIDE,
    asset_adjustment,
    company_multiple,
    risk_penalty,
    value_band,
)
from app.services.analysis.valuation_guards import structure


# ── Множитель по своим числам ──────────────────────────────────────────────

def test_company_multiple_uses_its_own_payout_and_return():
    """Никакого отдельного «коэффициента качества»: всё уже в формуле."""
    m = company_multiple(payout=100.0, roe=11.82, risk_free_rate=16.0, risk_premium=5.0)
    assert m.dividend_growth == pytest.approx(0.0)   # раздал всё — расти нечем
    assert m.value == pytest.approx(4.76, abs=0.01)


def test_higher_return_lifts_the_multiple_through_growth():
    """Высокая отдача капитала попадает в множитель через рост, а не мимо."""
    modest = company_multiple(50.0, 10.0, 16.0, 5.0)
    strong = company_multiple(50.0, 20.0, 16.0, 5.0)
    assert strong.dividend_growth > modest.dividend_growth
    assert strong.value > modest.value


def test_extra_premium_lowers_the_multiple():
    base = company_multiple(50.0, 12.0, 16.0, 5.0)
    penalised = company_multiple(50.0, 12.0, 16.0, 5.0, extra_premium=3.0)
    assert penalised.value < base.value
    assert penalised.required_return == pytest.approx(base.required_return + 3.0)


def test_company_multiple_needs_a_premium():
    assert company_multiple(50.0, 12.0, 16.0, None) is None


# ── Надбавка за риск ───────────────────────────────────────────────────────

def test_penalty_sums_the_three_signals():
    penalty = risk_penalty("разбросано", "fragile", history_years=3)
    assert penalty.spread == PENALTY_SPREAD_WIDE
    assert penalty.coverage == PENALTY_COVERAGE_FRAGILE
    assert penalty.history == PENALTY_HISTORY_THIN
    assert penalty.total == pytest.approx(5.5)
    assert len(penalty.notes) == 3


def test_clean_company_gets_no_penalty():
    penalty = risk_penalty("ровно", "ok", history_years=15)
    assert penalty.total == 0.0
    assert penalty.notes == []


def test_unknown_is_not_punished():
    """Незаполненное поле — не то же, что плохой показатель."""
    assert risk_penalty(None, None, None).total == 0.0
    assert risk_penalty(None, "unknown", None).total == 0.0


def test_history_penalty_has_two_steps():
    assert risk_penalty(None, None, 6).history == pytest.approx(1.0)
    assert risk_penalty(None, None, 4).history == pytest.approx(2.0)
    assert risk_penalty(None, None, 8).history == 0.0


# ── Поправка на активы, гл. 34 ─────────────────────────────────────────────

def test_excess_assets_reproduce_the_book_example():
    """⅔ × 100 = 66,7; 66,7 − 30 = 36,7; 30 + ⅓ × 36,7 = 42,2.

    В книге напечатано 42: авторы округлили промежуточные 67 и 37.
    """
    adjusted, note = asset_adjustment(value=30.0, book_value_per_share=100.0)
    assert adjusted == pytest.approx(42.22, abs=0.01)
    assert "активы избыточны" in note
    assert ASSET_WEIGHT == pytest.approx(2 / 3)


def test_shortfall_of_assets_trims_the_excess():
    """Оценка 300 при балансовой 100: превышение над 200 срезано на четверть."""
    adjusted, note = asset_adjustment(value=300.0, book_value_per_share=100.0)
    assert adjusted == pytest.approx(275.0)
    assert "активов не хватает" in note


def test_ordinary_case_is_left_alone():
    """Между ⅔ балансовой и двойной балансовой формула не вмешивается."""
    adjusted, note = asset_adjustment(value=150.0, book_value_per_share=100.0)
    assert adjusted == pytest.approx(150.0)
    assert note is None


def test_asset_adjustment_without_book_value():
    assert asset_adjustment(100.0, None) == (100.0, None)
    assert asset_adjustment(100.0, 0.0) == (100.0, None)
    assert asset_adjustment(None, 100.0) == (None, None)


# ── Полоса стоимости ───────────────────────────────────────────────────────

def clean_band(**kw):
    params = dict(
        payout=50.0, roe=12.0, risk_free_rate=16.0, risk_premium=5.0,
        normal_earnings={"прибыль": 100.0},
        book_value_per_share=500.0,
        structure=structure(1600.0, 200.0),   # покрытие 8x — спокойно
        stability_label="ровно",
        history_years=15,
    )
    params.update(kw)
    return value_band(**params)


def test_band_has_two_bounds_and_a_width():
    band = clean_band(stability_label="разбросано")
    assert band.low is not None and band.high is not None
    assert band.high > band.low
    assert band.width > 1.0


def test_clean_company_gets_a_narrow_band():
    """Ровная компания с длинной историей штрафа не получает — полоса схлопывается."""
    band = clean_band()
    assert band.penalty.total == 0.0
    assert band.width == pytest.approx(1.0)


def test_risky_company_gets_a_wider_band():
    narrow = clean_band().width
    wide = clean_band(stability_label="разбросано", history_years=4).width
    assert wide > narrow


def test_excessive_debt_refuses_valuation_outright():
    """Гл. 33, с. 618: к таким компаниям формальная оценка неприменима."""
    band = clean_band(structure=structure(1600.0, 800.0))   # покрытие 2,0x
    assert band.refused is True
    assert band.low is None
    assert "непредсказуемым" in band.reason


def test_three_ladders_give_three_valuations():
    band = clean_band(normal_earnings={
        "прибыль": 100.0, "деньги": 60.0, "прибыль владельца": 40.0,
    })
    assert [item.name for item in band.ladders] == ["прибыль", "деньги", "прибыль владельца"]
    # Расхождение лестниц растягивает полосу шире, чем одна надбавка за риск.
    assert band.ladders[0].value == pytest.approx(band.ladders[2].value * 2.5)
    assert band.width > 1.5


def test_book_value_works_as_a_floor_under_the_low_ladders():
    """Поправка на избыток активов подтягивает нижние лестницы вверх.

    Компания, зарабатывающая мало при большой балансовой стоимости, не может
    стоить произвольно дёшево: две трети активов идут в счёт (гл. 34, с. 634).
    Поэтому лестница «прибыль владельца» с оценкой 133 поднимается до 200.
    """
    band = clean_band(normal_earnings={"прибыль владельца": 40.0},
                      book_value_per_share=500.0)
    ladder = band.ladders[0]
    assert ladder.value == pytest.approx(133.2, abs=0.5)
    assert ladder.adjusted == pytest.approx(199.9, abs=0.5)
    assert "активы избыточны" in ladder.asset_note


def test_width_ignores_the_asset_adjustment():
    """Поправка на активы стягивает границы и о качестве ничего не говорит.

    Компания с большой балансовой стоимостью и малой прибылью получает
    подъём обеих границ к ⅔ активов. Если мерить ширину после подъёма,
    надбавка за риск исчезает из виду — а она и есть высказывание о качестве.
    """
    band = clean_band(stability_label="разбросано", history_years=4,
                      normal_earnings={"прибыль": 20.0},
                      book_value_per_share=500.0)
    assert band.asset_lift > 1.5                    # поправка сработала сильно
    assert band.high > band.high_by_earnings
    assert band.width == pytest.approx(
        band.high_by_earnings / band.low_by_earnings, abs=0.01)
    assert band.width > 1.2                         # штраф за риск виден


def test_band_reports_both_before_and_after_assets():
    band = clean_band(normal_earnings={"прибыль": 20.0})
    payload = band.as_dict()
    assert payload["low_by_earnings"] < payload["low"]
    assert payload["asset_lift"] > 1.0


def test_growth_cap_unblocks_a_high_return_company():
    """Без потолка компания с ROE 30% оценке не поддаётся вовсе."""
    refused = clean_band(roe=30.0, payout=20.0)
    assert refused.refused is True
    assert "бесконечность" in refused.reason

    allowed = clean_band(roe=30.0, payout=20.0, growth_cap=9.0)
    assert allowed.refused is False
    assert allowed.growth == pytest.approx(9.0)
    assert allowed.growth_uncapped == pytest.approx(24.0)
    assert allowed.growth_capped is True


def test_capped_growth_is_warned_about_not_hidden():
    """Подрезанный рост без пометки читался бы как настоящий."""
    band = clean_band(roe=30.0, payout=20.0, growth_cap=9.0)
    assert any("подрезан" in w for w in band.warnings)
    assert any("малом знаменателе" in w for w in band.warnings)


def test_slow_company_is_not_touched_by_the_cap():
    with_cap = clean_band(growth_cap=9.0)
    without = clean_band()
    assert with_cap.growth_capped is False
    assert with_cap.multiple_high == without.multiple_high
    assert not any("подрезан" in w for w in with_cap.warnings)


def test_weak_cash_backing_is_warned_about_not_hidden():
    band = clean_band(cash_backing=0.3)
    assert band.low is not None            # оценка считается
    assert any("деньгами" in w for w in band.warnings)


def test_short_history_is_warned_about():
    band = clean_band(history_years=6)
    assert any("вместо десяти" in w for w in band.warnings)


def test_loss_making_normal_earnings_refuse_the_band():
    band = clean_band(normal_earnings={"прибыль": -50.0})
    assert band.refused is True
    assert "не положительна" in band.reason


def test_zero_payout_refuses_with_the_formula_reason():
    band = clean_band(payout=0.0)
    assert band.refused is True
    assert "возвращать нечего" in band.reason


def test_band_is_serialisable():
    payload = clean_band(stability_label="умеренно").as_dict()
    assert payload["low"] and payload["high"]
    assert payload["penalty"]["total"] > 0
    assert payload["ladders"][0]["name"] == "прибыль"
