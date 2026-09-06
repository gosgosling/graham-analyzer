"""Проверки базового множителя рынка.

Опорный пример — расчёт авторов для S&P 400 на 1987 год, гл. 32, с. 605–606.
"""

import pytest

from app.services.analysis.market_multiple import (
    FRAGILE_SPREAD,
    HISTORIC_AVERAGE,
    MIN_SPREAD,
    SP400_1987,
    base_multiple,
    implied_growth,
    implied_premium,
    observed_payout,
    paired_multiples,
    payout_ladder,
    sensitivity,
    growth_is_capped,
    sustainable_growth,
)


# ── Книжный пример ─────────────────────────────────────────────────────────

def test_sp400_1987_reproduces_the_book():
    """0,46 / (0,1125 − 0,0750) = 12,27."""
    result = base_multiple(**SP400_1987)
    assert result.required_return == pytest.approx(11.25)
    assert result.spread == pytest.approx(3.75)
    assert result.value == pytest.approx(12.27, abs=0.01)
    assert result.problem is None


def test_earnings_yield_is_the_inverse():
    result = base_multiple(**SP400_1987)
    assert result.earnings_yield == pytest.approx(8.15, abs=0.01)


def test_historic_average_matches_the_book():
    assert HISTORIC_AVERAGE == 13.8


# ── Множитель определяется зазором K − g ───────────────────────────────────

@pytest.mark.parametrize(
    "growth, expected_spread, expected_value",
    [
        (7.50, 3.75, 12.27),
        (6.25, 5.00, 9.20),
        (9.25, 2.00, 23.00),
    ],
)
def test_multiple_is_driven_by_the_spread(growth, expected_spread, expected_value):
    """Сдвиг роста на пункт-полтора меняет ответ вдвое."""
    result = base_multiple(46.0, 8.5, 2.75, growth)
    assert result.spread == pytest.approx(expected_spread)
    assert result.value == pytest.approx(expected_value, abs=0.01)


def test_russian_rates_give_a_much_lower_multiple():
    """При ставке ОФЗ 15% формула честно даёт около четырёх, а не тринадцать.

    Подгонять этот ответ под американский диапазон 8,9–18,8 нельзя: реакция
    на ставку — единственное, что формула умеет.
    """
    result = base_multiple(payout=50.0, risk_free_rate=15.0,
                           risk_premium=5.0, dividend_growth=8.0)
    assert result.required_return == pytest.approx(20.0)
    assert result.value == pytest.approx(4.17, abs=0.01)
    assert result.value < 8.9      # ниже нижней границы США
    assert result.problem is None  # и это не повод отказываться считать


# ── Отказы считать ─────────────────────────────────────────────────────────

def test_growth_above_required_return_is_refused_with_a_reason():
    result = base_multiple(46.0, 8.5, 2.75, 12.0)
    assert result.value is None
    assert "бесконечность" in result.problem


def test_growth_equal_to_required_return_is_refused():
    result = base_multiple(46.0, 8.5, 2.75, 11.25)
    assert result.value is None
    assert result.spread == pytest.approx(0.0)
    assert result.problem is not None


def test_tiny_spread_is_refused_as_meaningless():
    result = base_multiple(46.0, 8.5, 2.75, 10.75)   # зазор 0,5 п.п.
    assert result.spread == pytest.approx(0.5)
    assert result.spread < MIN_SPREAD
    assert result.value is None
    assert "погрешностью входа" in result.problem


def test_zero_payout_is_refused():
    result = base_multiple(0.0, 8.5, 2.75, 5.0)
    assert result.value is None
    assert "возвращать нечего" in result.problem


def test_missing_input_returns_nothing_at_all():
    """Нет входа — нет объекта: это не отказ считать, а нечего считать."""
    assert base_multiple(None, 8.5, 2.75, 7.5) is None
    assert base_multiple(46.0, None, 2.75, 7.5) is None
    assert base_multiple(46.0, 8.5, None, 7.5) is None
    assert base_multiple(46.0, 8.5, 2.75, None) is None


def test_refusal_still_reports_the_inputs():
    """Отказ должен показывать, на чём споткнулся."""
    payload = base_multiple(46.0, 8.5, 2.75, 12.0).as_dict()
    assert payload["value"] is None
    assert payload["problem"]
    assert payload["required_return"] == pytest.approx(11.25)
    assert payload["dividend_growth"] == 12.0


# ── Хрупкость ──────────────────────────────────────────────────────────────

def test_narrow_spread_is_flagged_fragile_but_still_counted():
    result = base_multiple(46.0, 8.5, 2.75, 9.25)   # зазор 2,0 п.п.
    assert result.value is not None
    assert result.spread < FRAGILE_SPREAD
    assert result.fragile is True


def test_wide_spread_is_not_fragile():
    assert base_multiple(46.0, 8.5, 2.75, 6.25).fragile is False


# ── Чувствительность к премии за риск ──────────────────────────────────────

def test_sensitivity_shows_the_cost_of_the_risk_premium_guess():
    result = base_multiple(**SP400_1987)
    rows = sensitivity(result)
    assert [r["risk_premium_shift"] for r in rows] == [-1.0, -0.5, 0.5, 1.0]

    lower = next(r for r in rows if r["risk_premium_shift"] == -1.0)
    higher = next(r for r in rows if r["risk_premium_shift"] == 1.0)
    # Пункт премии в обе стороны — и множитель ходит от 9,7 до 16,7.
    assert lower["value"] == pytest.approx(16.73, abs=0.01)
    assert higher["value"] == pytest.approx(9.68, abs=0.01)
    assert higher["value"] < result.value < lower["value"]


def test_sensitivity_reports_a_shift_that_breaks_the_formula():
    result = base_multiple(46.0, 8.5, 2.75, 10.5)   # зазор 0,75 → уже отказ
    assert result.value is None
    assert sensitivity(result) == []


def test_sensitivity_carries_problems_of_shifted_variants():
    result = base_multiple(46.0, 8.5, 2.75, 9.75)  # зазор 1,5 — считается
    rows = sensitivity(result)
    broken = next(r for r in rows if r["risk_premium_shift"] == -1.0)
    assert broken["value"] is None
    assert broken["problem"] is not None


# ── Выплата, посчитанная по базе ───────────────────────────────────────────

def test_observed_payout_is_aggregate_not_average():
    """Сбербанк весит больше Ленэнерго — рынок это взвешенная сумма."""
    pairs = [(100.0, 1000.0), (9.0, 10.0)]   # 10% у гиганта, 90% у карлика
    result = observed_payout(pairs)
    assert result.payout == pytest.approx(10.79, abs=0.01)   # не 50%
    assert result.companies == 2


def test_observed_payout_keeps_loss_making_years():
    """Убыток — часть того, что рынок заработал, и из знаменателя не уходит."""
    with_loss = observed_payout([(50.0, 100.0), (0.0, -50.0)])
    assert with_loss.total_profit == pytest.approx(50.0)
    assert with_loss.payout == pytest.approx(100.0)

    without_loss = observed_payout([(50.0, 100.0)])
    assert without_loss.payout == pytest.approx(50.0)


def test_observed_payout_undefined_when_market_lost_money():
    result = observed_payout([(10.0, -100.0), (0.0, -50.0)])
    assert result.payout is None
    assert result.total_profit == pytest.approx(-150.0)


def test_observed_payout_skips_incomplete_pairs():
    result = observed_payout([(50.0, 100.0), (None, 100.0), (10.0, None)])
    assert result.companies == 1
    assert result.payout == pytest.approx(50.0)


def test_observed_payout_on_nothing():
    result = observed_payout([])
    assert result.payout is None
    assert result.companies == 0
    assert result.as_dict()["total_profit"] == 0


# ── Обратный ход: что рынок закладывает в цену ─────────────────────────────

def test_implied_growth_inverts_the_formula():
    """Подставив множитель самой формулы, получаем исходный рост."""
    result = base_multiple(**SP400_1987)
    back = implied_growth(
        SP400_1987["payout"], SP400_1987["risk_free_rate"],
        SP400_1987["risk_premium"], result.value,
    )
    assert back == pytest.approx(SP400_1987["dividend_growth"], abs=0.01)


def test_implied_premium_inverts_the_formula():
    result = base_multiple(**SP400_1987)
    back = implied_premium(
        SP400_1987["payout"], SP400_1987["risk_free_rate"],
        SP400_1987["dividend_growth"], result.value,
    )
    assert back == pytest.approx(SP400_1987["risk_premium"], abs=0.01)


def test_implied_growth_reads_the_russian_market():
    """P/E 4,35 при ставке 16% и премии 5 означает рост около 10,6%."""
    assert implied_growth(45.32, 16.0, 5.0, 4.35) == pytest.approx(10.58, abs=0.05)


def test_higher_price_implies_higher_growth():
    cheap = implied_growth(45.0, 16.0, 5.0, 3.0)
    dear = implied_growth(45.0, 16.0, 5.0, 6.0)
    assert dear > cheap


def test_implied_premium_can_go_negative():
    """Дорогой рынок при слабом росте и высокой ставке — премия ниже нуля.

    Множитель 20 при выплате 45% даёт дивидендную доходность 2,25%; вместе с
    ростом 2% это 4,25% против 16% по ОФЗ. Значит покупатель соглашается на
    меньшее, чем даёт безрисковая бумага, — и либо рост занижен, либо в цене
    сидит то, чего в модели нет.
    """
    assert implied_premium(45.0, 16.0, 2.0, 20.0) == pytest.approx(-11.75, abs=0.01)


def test_implied_premium_vanishes_at_modest_growth():
    """Российский случай, и он неуютный.

    P/E 4,35 при ОФЗ 16% и росте дивидендов 6% даёт премию за риск 0,4 п.п. —
    то есть рынок почти не доплачивает за то, что акция не облигация. Либо
    рост на самом деле выше, либо премии тут действительно нет.
    """
    assert implied_premium(45.32, 16.0, 6.0, 4.35) == pytest.approx(0.42, abs=0.05)


def test_the_two_inversions_are_consistent():
    """Оба обратных хода описывают одну точку: рост 10,58% ↔ премия 5 п.п."""
    growth = implied_growth(45.32, 16.0, 5.0, 4.35)
    premium = implied_premium(45.32, 16.0, growth, 4.35)
    assert premium == pytest.approx(5.0, abs=0.05)


def test_implied_values_need_every_input():
    assert implied_growth(None, 16.0, 5.0, 4.35) is None
    assert implied_growth(45.0, 16.0, 5.0, 0) is None
    assert implied_growth(0.0, 16.0, 5.0, 4.35) is None
    assert implied_premium(45.0, None, 5.0, 4.35) is None
    assert implied_premium(45.0, 16.0, 5.0, None) is None


# ── Устойчивый рост: g не угадывается, а выводится ─────────────────────────

def test_sustainable_growth_is_retained_earnings_at_work():
    """Раздал 45% при отдаче 11,7% — расти можешь на 6,4%."""
    assert sustainable_growth(11.7, 45.32) == pytest.approx(6.4, abs=0.01)


def test_full_payout_leaves_nothing_to_grow_on():
    assert sustainable_growth(20.0, 100.0) == pytest.approx(0.0)


def test_payout_above_profit_eats_the_capital():
    """Раздали больше, чем заработали, — дивиденды обязаны снижаться."""
    assert sustainable_growth(9.0, 108.6) < 0


def test_no_payout_means_growth_equals_return():
    assert sustainable_growth(15.0, 0.0) == pytest.approx(15.0)


def test_sustainable_growth_needs_both_inputs():
    assert sustainable_growth(None, 45.0) is None
    assert sustainable_growth(11.7, None) is None


def test_sustainable_growth_closes_the_loop_with_the_multiple():
    """Выведенный рост подставляется в формулу и даёт осмысленный множитель."""
    growth = sustainable_growth(11.7, 45.32)
    result = base_multiple(45.32, 16.0, 5.0, growth)
    assert result.value == pytest.approx(3.1, abs=0.05)


# ── Две ставки: сегодняшняя и нормализованная ──────────────────────────────

def test_paired_multiples_show_what_the_rate_costs():
    """Одна и та же компания при ставке 16% и 10% стоит вдвое разного."""
    pair = paired_multiples(45.32, 16.0, 5.0, 8.0, normalized_risk_free_rate=10.0)
    assert pair["current"].value == pytest.approx(3.49, abs=0.01)
    assert pair["normalized"].value == pytest.approx(6.47, abs=0.01)
    assert pair["rate_effect"] == pytest.approx(1.85, abs=0.01)


def test_paired_multiples_without_a_normalized_rate():
    pair = paired_multiples(45.32, 16.0, 5.0, 8.0)
    assert pair["current"].value is not None
    assert pair["normalized"] is None
    assert pair["rate_effect"] is None


def test_rate_effect_undefined_when_a_side_refuses_to_count():
    """Нормализованная ставка ниже роста — формула отказывается, и это видно."""
    pair = paired_multiples(45.32, 16.0, 5.0, 12.0, normalized_risk_free_rate=6.0)
    assert pair["current"].value is not None
    assert pair["normalized"].value is None
    assert pair["normalized"].problem is not None
    assert pair["rate_effect"] is None


def test_normalized_rate_equal_to_current_changes_nothing():
    pair = paired_multiples(45.32, 16.0, 5.0, 8.0, normalized_risk_free_rate=16.0)
    assert pair["rate_effect"] == pytest.approx(1.0)


# ── Лестница выплаты ───────────────────────────────────────────────────────

def ladder():
    return payout_ladder(roe=11.82, risk_free_rate=16.0, risk_premium=5.0,
                         normalized_risk_free_rate=10.0)


def test_ladder_covers_the_whole_range_in_steps():
    rows = ladder()
    assert [r["payout"] for r in rows][:3] == [0, 5, 10]
    assert rows[-1]["payout"] == 100
    assert len(rows) == 21


def test_growth_falls_as_payout_rises():
    """Рост и выплата связаны: чем больше раздал, тем меньше на чём расти."""
    rows = {r["payout"]: r for r in ladder()}
    assert rows[0]["growth"] == pytest.approx(11.82)     # ничего не раздал
    assert rows[50]["growth"] == pytest.approx(5.91)
    assert rows[100]["growth"] == pytest.approx(0.0)     # раздал всё


def test_full_payer_deserves_the_highest_multiple():
    rows = {r["payout"]: r for r in ladder()}
    assert rows[100]["multiple"] == pytest.approx(4.76, abs=0.01)
    assert rows[50]["multiple"] == pytest.approx(3.31, abs=0.01)
    assert rows[100]["multiple"] > rows[50]["multiple"]


def test_ratio_between_full_and_half_payer_matches_market_observation():
    """Плательщик 100% заслуживает примерно 1,44 множителя половинного.

    Наблюдение рынка: исторически российские компании со стопроцентной
    выплатой торговались по P/E 8–8,5 против рыночных 5,5–6 — отношение 1,43.
    Формула приходит к тому же, ничего о котировках не зная.
    """
    rows = {r["payout"]: r for r in ladder()}
    assert rows[100]["multiple"] / rows[50]["multiple"] == pytest.approx(1.44, abs=0.02)


def test_paying_nothing_is_worth_nothing():
    """Не парадокс, а точная формулировка того, что оценивает Гордон."""
    zero = ladder()[0]
    assert zero["payout"] == 0
    assert zero["multiple"] is None
    assert "возвращать нечего" in zero["problem"]


def test_dividend_yield_equals_earnings_yield_for_a_full_payer():
    rows = {r["payout"]: r for r in ladder()}
    full = rows[100]
    assert full["dividend_yield"] == pytest.approx(100 / full["multiple"], abs=0.05)
    assert full["dividend_yield"] == pytest.approx(21.0, abs=0.05)


def test_normalized_rate_lifts_every_rung():
    for row in ladder():
        if row["multiple"] and row["normalized_multiple"]:
            assert row["normalized_multiple"] > row["multiple"]


def test_high_return_company_breaks_the_formula_at_low_payout():
    """Рост выше требуемой доходности — формула отказывается, и это видно."""
    rows = {r["payout"]: r for r in payout_ladder(
        roe=30.0, risk_free_rate=16.0, risk_premium=5.0)}
    assert rows[10]["multiple"] is None
    assert "бесконечность" in rows[10]["problem"]
    assert rows[100]["multiple"] is not None


def test_ladder_without_inputs_is_empty():
    assert payout_ladder(None, 16.0, 5.0) == []
    assert payout_ladder(11.82, None, 5.0) == []


# ── Потолок роста ──────────────────────────────────────────────────────────

def test_cap_only_lowers_never_raises():
    """У медленной компании потолок ничего не меняет."""
    assert sustainable_growth(11.82, 45.32, cap=9.0) == pytest.approx(6.46, abs=0.01)
    assert sustainable_growth(11.82, 45.32) == pytest.approx(6.46, abs=0.01)


def test_cap_trims_a_tiny_denominator_company():
    """Делимобиль: ROE 75% при капитале 2,6 млрд — рост от малого знаменателя."""
    assert sustainable_growth(74.8, 20.0) == pytest.approx(59.84, abs=0.01)
    assert sustainable_growth(74.8, 20.0, cap=9.0) == pytest.approx(9.0)


def test_cap_leaves_negative_growth_alone():
    """Раздали больше, чем заработали: рост отрицателен, потолок ни при чём."""
    assert sustainable_growth(9.0, 108.6, cap=9.0) < 0


def test_capped_flag_tells_the_two_cases_apart():
    assert growth_is_capped(74.8, 20.0, 9.0) is True
    assert growth_is_capped(11.82, 45.32, 9.0) is False
    assert growth_is_capped(74.8, 20.0, None) is False
    assert growth_is_capped(None, 20.0, 9.0) is False


def test_cap_unblocks_a_multiple_the_formula_refused():
    """Без потолка формула отказывается: рост обгоняет требуемую доходность."""
    without = base_multiple(20.0, 16.0, 5.0, sustainable_growth(30.0, 20.0))
    assert without.value is None
    assert "бесконечность" in without.problem

    with_cap = base_multiple(20.0, 16.0, 5.0, sustainable_growth(30.0, 20.0, cap=9.0))
    assert with_cap.value == pytest.approx(1.67, abs=0.01)
