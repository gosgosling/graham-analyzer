"""Проверки способности получать прибыль.

Опорные примеры взяты из Коттла–Мюррея–Блока, гл. 30, — там, где книга даёт
и входные числа, и ответ.
"""

import pytest

from app.services.analysis.earning_power import (
    CASH_BACKING_WEAK,
    YearPoint,
    analyze,
    capped_at_peak,
    cash_backing,
    direction,
    estimate,
    graham_growth,
    latest_book_value,
    own_cash_flow,
    split_factors,
    trend_value,
    passes_graham_growth,
    buyback_payout,
    payout_over_window,
    window_average,
    _per_share,
    _to_equity,
)


def series(values, attr="eps", first_year=2016, **extra):
    """Ряд одной величины: значение на год, начиная с first_year."""
    return [
        YearPoint(year=first_year + i, **{attr: v}, **extra)
        for i, v in enumerate(values)
    ]


# ── Средняя за окно ────────────────────────────────────────────────────────

def test_average_takes_last_window_years():
    points = series([1, 2, 3, 4, 5, 6, 7])  # 2016..2022
    avg = window_average(points, "eps", 3)
    assert avg.value == pytest.approx(6.0)  # 5, 6, 7
    assert (avg.first_year, avg.last_year) == (2020, 2022)
    assert avg.complete


def test_average_reports_incomplete_window():
    """Дыра в середине не должна молча превращать окно в более короткое."""
    points = [YearPoint(2020, eps=10), YearPoint(2022, eps=20)]
    avg = window_average(points, "eps", 5)
    assert avg.value == pytest.approx(15.0)
    assert avg.years_used == 2
    assert avg.complete is False


def test_average_window_longer_than_history():
    points = series([4, 6])
    avg = window_average(points, "eps", 10)
    assert avg.years_used == 2
    assert avg.complete is False


def test_average_records_peak_and_zero_crossing():
    points = series([5, -3, 8, 2])
    avg = window_average(points, "eps", 4)
    assert avg.peak == 8
    assert avg.crosses_zero is True

    positive = window_average(series([5, 3, 8, 2]), "eps", 4)
    assert positive.crosses_zero is False


def test_average_returns_none_without_data():
    assert window_average([YearPoint(2020)], "eps", 3) is None
    assert window_average([], "eps", 3) is None


def test_average_respects_end_year():
    points = series([1, 2, 3, 4, 5, 6, 7])
    avg = window_average(points, "eps", 3, end_year=2019)
    assert avg.value == pytest.approx(3.0)  # 2, 3, 4
    assert (avg.first_year, avg.last_year) == (2017, 2019)


# ── Два способа: McDonald's, с. 566 ────────────────────────────────────────

def test_mcdonalds_two_methods_diverge_for_a_grower():
    """Книжный пример: средняя EPS 1,90, а через отдачу на капитал — 3,79.

    У растущей компании способы обязаны разойтись, и разойтись именно в эту
    сторону: средняя за десять лет ниже, потому что тянет вниз начало ряда.
    """
    # Ряд, растущий с 1,00 до 2,80 при средней 1,90 и ROE около 20,6%.
    eps = [1.00, 1.20, 1.40, 1.60, 1.80, 2.00, 2.20, 2.40, 2.60, 2.80]
    points = [
        YearPoint(2016 + i, eps=v, roe=20.6, book_value_per_share=18.50)
        for i, v in enumerate(eps)
    ]
    result = estimate(points, 10, "eps", "roe")

    assert result.per_share.value == pytest.approx(1.90)
    # 20,6% × 18,50 = 3,811; в книге напечатано 3,79 — там ROE округлён.
    assert result.return_based == pytest.approx(3.811)
    assert result.divergence == pytest.approx(2.006, abs=0.01)


def test_return_based_uses_latest_book_value():
    """Способ B опирается на накопленный капитал, а не на капитал начала ряда."""
    points = [
        YearPoint(2020, eps=1.0, roe=10.0, book_value_per_share=50.0),
        YearPoint(2021, eps=1.0, roe=10.0, book_value_per_share=100.0),
    ]
    assert latest_book_value(points) == 100.0
    assert estimate(points, 2, "eps", "roe").return_based == pytest.approx(10.0)


def test_estimate_without_book_value_has_no_method_b():
    points = series([2, 4], attr="eps")
    result = estimate(points, 2, "eps", "roe")
    assert result.per_share.value == pytest.approx(3.0)
    assert result.return_based is None
    assert result.divergence is None


def test_divergence_undefined_when_a_side_is_not_positive():
    points = [
        YearPoint(2020, eps=-5.0, roe=-10.0, book_value_per_share=100.0),
        YearPoint(2021, eps=-5.0, roe=-10.0, book_value_per_share=100.0),
    ]
    assert estimate(points, 2, "eps", "roe").divergence is None


# ── Средняя врёт направленно: табл. 30.3, с. 570 ───────────────────────────

@pytest.mark.parametrize(
    "values, relation",
    [
        ([1, 2, 3, 4, 5, 6], "below"),      # рост:    средняя ниже текущей
        ([6, 6, 6, 6, 6, 6], "equal"),      # ровно:   средняя равна текущей
        ([11, 10, 9, 8, 7, 6], "above"),    # падение: средняя выше текущей
    ],
)
def test_average_is_biased_by_direction(values, relation):
    """Чем сильнее рост, тем ниже средняя относительно текущей, и наоборот."""
    points = series(values)
    avg = window_average(points, "eps", len(values)).value
    current = values[-1]
    if relation == "below":
        assert avg < current
    elif relation == "equal":
        assert avg == pytest.approx(current)
    else:
        assert avg > current


def test_direction_labels():
    assert direction(series([1, 2, 3, 4, 5, 6]), "eps", 6).label == "рост"
    assert direction(series([6, 6, 6, 6, 6, 6]), "eps", 6).label == "ровно"
    assert direction(series([11, 10, 9, 8, 7, 6]), "eps", 6).label == "падение"


def test_change_is_not_rounded_below_the_threshold():
    """Рост ровно на треть обязан проходить порог, а не спотыкаться об округление."""
    d = graham_growth(series([3.0] * 3 + [3.5] * 4 + [4.0] * 3))
    assert d.change == pytest.approx(1 / 3)
    assert d.as_dict()["change"] == 0.3333


def test_direction_compares_halves_and_names_the_years():
    d = direction(series([1, 1, 1, 3, 3, 3]), "eps", 6)
    assert d.older == pytest.approx(1.0)
    assert d.newer == pytest.approx(3.0)
    assert d.older_years == (2016, 2017, 2018)
    assert d.newer_years == (2019, 2020, 2021)
    assert d.change == pytest.approx(2.0)


def test_direction_needs_four_points():
    assert direction(series([1, 2, 3]), "eps", 3) is None


def test_direction_odd_length_drops_the_middle_year():
    """Середина ряда не должна попадать сразу в обе половины."""
    d = direction(series([1, 1, 99, 3, 3]), "eps", 5)
    assert d.older == pytest.approx(1.0)
    assert d.newer == pytest.approx(3.0)
    assert 2018 not in d.older_years and 2018 not in d.newer_years


# ── Тест роста защитного инвестора ─────────────────────────────────────────

def test_graham_growth_smooths_both_ends():
    """Не скользящие средние, а два конца десятилетия по три года каждый."""
    points = series([1, 1, 1, 2, 2, 2, 2, 3, 3, 3])
    growth = graham_growth(points)
    assert growth.older == pytest.approx(1.0)      # 2016-2018
    assert growth.newer == pytest.approx(3.0)      # 2023-2025
    assert growth.older_years == (2016, 2017, 2018)
    assert growth.newer_years == (2023, 2024, 2025)


def test_graham_growth_threshold_is_one_third():
    grew = series([3.0] * 3 + [3.5] * 4 + [4.0] * 3)     # +33,3%
    assert passes_graham_growth(graham_growth(grew)) is True

    barely = series([3.0] * 3 + [3.2] * 4 + [3.9] * 3)   # +30%
    assert passes_graham_growth(graham_growth(barely)) is False


def test_graham_growth_needs_two_full_ends():
    assert graham_growth(series([1, 2, 3, 4, 5])) is None


def test_passes_growth_is_none_without_data():
    assert passes_graham_growth(None) is None


# ── Ограничение по достигнутому пику ───────────────────────────────────────

def test_capped_at_peak_trims_forecast_above_history():
    points = series([1, 2, 3, 4, 5])
    avg = window_average(points, "eps", 5)
    assert capped_at_peak(9.0, avg) == 5.0     # выше пика нельзя
    assert capped_at_peak(4.0, avg) == 4.0     # ниже пика не трогаем


def test_capped_at_peak_passes_none_through():
    assert capped_at_peak(None, None) is None
    assert capped_at_peak(5.0, None) == 5.0


# ── Обеспеченность прибыли деньгами ────────────────────────────────────────

def test_cash_backing_flags_paper_profit():
    points = [
        YearPoint(2020 + i, eps=100.0, fcf_per_share=30.0) for i in range(5)
    ]
    backing = cash_backing(points, 5)
    assert backing["ratio"] == pytest.approx(0.3)
    assert backing["weak"] is True
    assert backing["complete"] is True


def test_cash_backing_healthy_company_is_not_flagged():
    points = [
        YearPoint(2020 + i, eps=100.0, fcf_per_share=90.0) for i in range(5)
    ]
    assert cash_backing(points, 5)["weak"] is False
    assert CASH_BACKING_WEAK == 0.6


def test_cash_backing_smooths_a_lumpy_capex_year():
    """За один год отношение проваливается, на окне — держится."""
    points = [
        YearPoint(2020, eps=100.0, fcf_per_share=95.0),
        YearPoint(2021, eps=100.0, fcf_per_share=95.0),
        YearPoint(2022, eps=100.0, fcf_per_share=-40.0),   # построили завод
        YearPoint(2023, eps=100.0, fcf_per_share=95.0),
        YearPoint(2024, eps=100.0, fcf_per_share=95.0),
    ]
    assert cash_backing(points, 1, end_year=2022)["weak"] is True   # один год
    assert cash_backing(points, 5)["weak"] is False                 # окно


def test_cash_backing_undefined_on_average_loss():
    points = [YearPoint(2020 + i, eps=-10.0, fcf_per_share=5.0) for i in range(3)]
    assert cash_backing(points, 3) is None


# ── Прибыль владельца ──────────────────────────────────────────────────────

def test_owner_earnings_sits_between_profit_and_cash_flow():
    """ПВ = прибыль + амортизация − капекс.

    У компании, которая тратит на основные средства ровно столько, сколько
    изнашивает, прибыль владельца совпадает с прибылью. Тратит больше —
    оказывается ниже.
    """
    steady = _owner(profit=100.0, depreciation=40.0, capex=40.0)
    assert steady == pytest.approx(100.0)

    building = _owner(profit=100.0, depreciation=40.0, capex=90.0)
    assert building == pytest.approx(50.0)


def _owner(profit, depreciation, capex):
    return profit + depreciation - capex


def test_owner_earnings_flows_through_analyze():
    points = [
        YearPoint(
            2020 + i,
            eps=100.0,
            owner_earnings_per_share=60.0,
            owner_earnings_to_equity=6.0,
            book_value_per_share=1000.0,
        )
        for i in range(5)
    ]
    result = analyze(points)
    assert result.owner[5].per_share.value == pytest.approx(60.0)
    assert result.owner[5].return_based == pytest.approx(60.0)
    assert result.as_dict()["owner"][5]["per_share"]["value"] == 60.0


def test_owner_earnings_absent_for_lenders():
    points = [YearPoint(2020 + i, eps=1.0, owner_earnings_per_share=1.0) for i in range(3)]
    assert analyze(points, with_cash=False).owner == {}


def test_owner_earnings_missing_when_a_term_is_absent():
    """Без амортизации это просто прибыль, без капекса — прибыль с завышением."""
    points = [YearPoint(2020 + i, eps=100.0) for i in range(5)]
    result = analyze(points)
    assert result.owner[5].per_share is None


# ── Пересчёт на акцию и на капитал ─────────────────────────────────────────

def test_per_share_converts_millions_to_roubles():
    assert _per_share(1000.0, 500_000) == pytest.approx(2000.0)


def test_per_share_and_return_guard_against_zero_and_none():
    assert _per_share(100.0, 0) is None
    assert _per_share(None, 1000) is None
    assert _to_equity(100.0, 0) is None
    assert _to_equity(None, 1000) is None


def test_to_equity_is_percent():
    assert _to_equity(150.0, 1000.0) == pytest.approx(15.0)


# ── Загрузка из кэша ───────────────────────────────────────────────────────

class _Row:
    """Строка кэша мультипликаторов — только поля про поток."""

    def __init__(self, ltm_fcf=None, ltm_core_fcf=None):
        self.ltm_fcf = ltm_fcf
        self.ltm_core_fcf = ltm_core_fcf


def test_core_flow_wins_over_gross():
    """У биржи в валовом потоке сидят клиентские деньги, считать надо не их.

    Мосбиржа за 2022 год: валовой поток 1 209 млрд против 179 млрд
    собственных. Разница — движение чужих денег.
    """
    row = _Row(ltm_fcf=1_208_888.5, ltm_core_fcf=178_957.8)
    assert own_cash_flow(row) == pytest.approx(178_957.8)


def test_gross_flow_used_when_there_is_nothing_to_clean():
    """У промышленной компании чужих денег нет — очищать нечего."""
    assert own_cash_flow(_Row(ltm_fcf=500.0)) == pytest.approx(500.0)


def test_negative_core_flow_is_not_treated_as_missing():
    """Отрицательный собственный поток — факт, а не отсутствие данных."""
    row = _Row(ltm_fcf=199_045.0, ltm_core_fcf=-57_645.0)   # Озон за 2024
    assert own_cash_flow(row) == pytest.approx(-57_645.0)


def test_no_flow_at_all():
    assert own_cash_flow(_Row()) is None


# ── Полный разбор ──────────────────────────────────────────────────────────

def full_points():
    return [
        YearPoint(
            2016 + i,
            eps=100.0 + 10 * i,
            fcf_per_share=80.0 + 8 * i,
            roe=15.0,
            fcf_to_equity=12.0,
            book_value_per_share=700.0 + 50 * i,
        )
        for i in range(10)
    ]


def test_analyze_fills_every_window():
    result = analyze(full_points())
    assert set(result.earnings) == {3, 5, 7, 10}
    assert set(result.cash) == {3, 5, 7, 10}
    assert set(result.owner) == {3, 5, 7, 10}
    assert result.book_value_per_share == pytest.approx(1150.0)
    assert result.growth is not None


def test_analyze_skips_cash_for_lenders():
    """У банка движение клиентских денег на порядок больше собственного."""
    result = analyze(full_points(), with_cash=False)
    assert result.earnings
    assert result.cash == {}
    assert result.backing == {}


def test_analyze_is_serialisable():
    payload = analyze(full_points()).as_dict()
    assert payload["earnings"][3]["per_share"]["value"] > 0
    assert payload["cash_backing"][5]["ratio"] == pytest.approx(0.8, abs=0.02)
    assert payload["graham_growth"]["label"] == "рост"
    assert payload["graham_growth_passes"] is True


def test_analyze_survives_a_hole_in_the_series():
    """У ЛУКОЙЛа за 2022 нет свободного потока — прибыль считаться должна."""
    points = [
        YearPoint(2020, eps=100.0, fcf_per_share=90.0, roe=10.0, book_value_per_share=1000.0),
        YearPoint(2021, eps=110.0, roe=11.0, book_value_per_share=1050.0),
        YearPoint(2022, eps=120.0, roe=12.0, book_value_per_share=1100.0),
    ]
    result = analyze(points)
    assert result.earnings[3].per_share.complete is True
    assert result.cash[3].per_share.years_used == 1
    assert result.cash[3].per_share.complete is False


def test_analyze_on_empty_history_returns_empty_estimates():
    result = analyze([YearPoint(2024)])
    assert result.earnings[3].per_share is None
    assert result.growth is None
    assert result.as_dict()["graham_growth"] is None


# ── Выплата за окно ────────────────────────────────────────────────────────

def dividend_series(pairs, first_year=2019):
    return [
        YearPoint(first_year + i, eps=eps, dividends_per_share=div)
        for i, (eps, div) in enumerate(pairs)
    ]


def test_payout_is_sum_to_sum_not_average_of_years():
    """Год с провальной прибылью не должен решать за весь период.

    У ЛУКОЙЛа за 2025-й дивиденд относится к прибыли как 505%; средняя по
    годам утащила бы выплату далеко за сто процентов, сумма к сумме — нет.
    """
    points = dividend_series([(1000.0, 500.0), (1000.0, 500.0), (100.0, 505.0)])
    assert payout_over_window(points, 3) == pytest.approx(71.67, abs=0.01)

    by_year = sum(d / e for e, d in
                  [(1000.0, 500.0), (1000.0, 500.0), (100.0, 505.0)]) / 3 * 100
    assert by_year > 200        # средняя по годам сказала бы бессмыслицу


def test_payout_over_a_steady_period():
    points = dividend_series([(100.0, 50.0)] * 7)
    assert payout_over_window(points, 7) == pytest.approx(50.0)


def test_payout_counts_years_without_dividends_as_zero():
    points = dividend_series([(100.0, 50.0), (100.0, None), (100.0, 50.0)])
    assert payout_over_window(points, 3) == pytest.approx(33.33, abs=0.01)


def test_payout_undefined_when_the_period_lost_money():
    points = dividend_series([(-100.0, 0.0), (-50.0, 0.0)])
    assert payout_over_window(points, 2) is None


def test_payout_needs_some_data():
    assert payout_over_window([YearPoint(2024)], 5) is None


def test_declared_dividend_without_an_amount_is_unknown_not_zero():
    """Отметка «выплаты были» при незанесённой сумме — пробел, а не отказ платить.

    У ФосАгро именно так: флаг стоит, сумма пустая. Считать это нулём значит
    объявить исправного плательщика скрягой и отказать ему в оценке.
    """
    points = [
        YearPoint(2022 + i, eps=100.0, dividends_per_share=None, dividends_declared=True)
        for i in range(3)
    ]
    assert payout_over_window(points, 3) is None


def test_company_that_truly_pays_nothing_gets_zero():
    """Отметка «выплат не было» — это утверждение, и оно означает ноль."""
    points = [
        YearPoint(2022 + i, eps=100.0, dividends_per_share=None, dividends_declared=False)
        for i in range(3)
    ]
    assert payout_over_window(points, 3) == pytest.approx(0.0)


def test_partial_amounts_are_enough_to_count():
    """Если хоть один год с суммой есть, ряд считается: пропуски идут нулями."""
    points = [
        YearPoint(2022, eps=100.0, dividends_per_share=50.0, dividends_declared=True),
        YearPoint(2023, eps=100.0, dividends_per_share=None, dividends_declared=True),
        YearPoint(2024, eps=100.0, dividends_per_share=50.0, dividends_declared=True),
    ]
    assert payout_over_window(points, 3) == pytest.approx(33.33, abs=0.01)


# ── Приведение к текущему числу акций ──────────────────────────────────────

def test_split_is_restated():
    """Норникель: акций в сто раз больше, капитал на месте — дробление."""
    factors = split_factors([
        (2022, 152_863_397, 1_100_000.0, 2_400_000.0),
        (2023, 152_863_397, 1_150_000.0, 2_470_000.0),
        (2024, 15_286_339_700, 1_400_000.0, 1_770_000.0),   # капитализация цела
    ])
    assert factors[2023] == pytest.approx(100.0)
    assert factors[2022] == pytest.approx(100.0)
    assert 2024 not in factors            # последний год приводить не к чему


def test_share_issue_is_not_restated():
    """Сегежа выпустила новые акции: размывание — настоящая потеря владельца.

    Стереть его приведением значило бы соврать в пользу компании: прежний
    держатель действительно стал владеть меньшей долей.
    """
    factors = split_factors([
        (2024, 15_690_000_000, 100_000.0, 30_000.0),
        (2025, 43_876_000_000, 260_000.0, 84_000.0),  # деньги пришли с акциями
    ])
    assert factors == {}


def test_buyback_is_not_restated():
    """Выкуп честно поднимает прибыль на каждую оставшуюся акцию."""
    factors = split_factors([
        (2008, 846_645_000, 1_468_986.0, 1_500_000.0),
        (2025, 586_922_000, 3_358_003.0, 2_717_330.0),
    ])
    assert factors == {}


def test_two_splits_multiply():
    factors = split_factors([
        (2020, 1_000_000, 500.0, 900.0),
        (2021, 2_000_000, 520.0, 950.0),
        (2022, 20_000_000, 560.0, 1_000.0),
    ])
    assert factors[2020] == pytest.approx(20.0)
    assert factors[2021] == pytest.approx(10.0)


def test_reverse_split_is_restated_too():
    """Обратное дробление ломает сопоставимость так же, в другую сторону."""
    factors = split_factors([
        (2023, 10_000_000, 900.0, 1_200.0), (2024, 1_000_000, 950.0, 1_100.0),
    ])
    assert factors[2023] == pytest.approx(0.1)


def test_without_equity_nothing_is_restated():
    """Промолчать безопаснее: не приведённый ряд виден глазом, стёртое — нет."""
    assert split_factors([
        (2023, 100_000, None, 500.0), (2024, 10_000_000, None, 500.0),
    ]) == {}


def test_without_market_cap_nothing_is_restated():
    """Позитив за 2020: акций 6,2 млрд при капитале 2,5 млрд, цены нет.

    Это ошибка ввода, а не обратное дробление. Приведение по такому числу
    раздуло бы дивиденд в 258 раз и отравило бы всю выплату за окно.
    """
    assert split_factors([
        (2020, 6_200_000_000, 2_523.0, None),
        (2021, 24_058_082, 3_503.0, 40_000.0),
    ]) == {}


def test_split_factors_need_a_series():
    assert split_factors([]) == {}
    assert split_factors([(2024, 1_000_000, 500.0, 900.0)]) == {}
    assert split_factors([(2024, None, 500.0, 900.0), (2025, 1_000, 500.0, 900.0)]) == {}


def test_absurd_payout_is_refused_as_broken_data():
    """Раздать втрое больше заработанного семь лет подряд нельзя."""
    points = [
        YearPoint(2020 + i, eps=10.0, dividends_per_share=500.0, dividends_declared=True)
        for i in range(3)
    ]
    assert payout_over_window(points, 3) is None


def test_payout_above_one_hundred_is_still_allowed():
    """Год-другой раздать больше прибыли — обычное дело, это не ошибка."""
    points = [
        YearPoint(2020 + i, eps=100.0, dividends_per_share=120.0, dividends_declared=True)
        for i in range(3)
    ]
    assert payout_over_window(points, 3) == pytest.approx(120.0)


def test_restated_series_averages_meaningfully():
    """Средняя по приведённому ряду — величина, а по сырому — бессмыслица."""
    raw = [1398.7, 8.7, 10.0]                       # как лежит в базе
    restated = [1398.7 / 100, 8.7, 10.0]            # после приведения
    assert sum(raw) / 3 > 400                       # средняя ни на что не похожа
    assert 9 < sum(restated) / 3 < 12               # а эта описывает компанию


# ── Выкуп как часть возврата владельцу ─────────────────────────────────────

def buyback_series(rows, first_year=2019):
    """rows: (акций, цена, eps) по годам."""
    return [
        YearPoint(first_year + i, eps=eps, shares_normalized=float(shares),
                  price_normalized=float(price))
        for i, (shares, price, eps) in enumerate(rows)
    ]


def test_buyback_counts_as_return_of_capital():
    """Выкуп доносит деньги владельцу так же, как дивиденд.

    Выкуплено 100 акций по 10 ₽ — потрачено 1 000 ₽. Прибыль за окно из двух
    лет: 10 ₽ × 1 000 акций плюс 10 ₽ × 900 акций = 19 000 ₽. Возврат выкупом
    составил 5,26% заработанного.
    """
    points = buyback_series([(1000, 10.0, 10.0), (900, 10.0, 10.0)])
    assert buyback_payout(points, 2) == pytest.approx(5.26, abs=0.01)


def test_issue_of_shares_is_negative_return():
    """Эмиссия не возвращает капитал, а забирает: доля владельца уменьшилась."""
    points = buyback_series([(1000, 10.0, 10.0), (1200, 10.0, 10.0)])
    assert buyback_payout(points, 2) < 0


def test_steady_share_count_returns_nothing():
    points = buyback_series([(1000, 10.0, 10.0)] * 3)
    assert buyback_payout(points, 3) == pytest.approx(0.0)


def test_implausible_share_step_refuses_to_count():
    """У Позитива за 2020 записано 6,2 млрд акций вместо 24 млн.

    Без границы это превращается в «выкуп» семнадцати тысяч процентов
    прибыли. Что произошло на самом деле — нераспознанное дробление или
    опечатка — из ряда не видно, и считать по нему нельзя.
    """
    points = buyback_series([(6_200_000_000, 1.0, 0.2), (24_058_082, 840.0, 79.6)])
    assert buyback_payout(points, 2) is None


def test_real_buyback_of_a_third_is_within_bounds():
    """Магнит выкупил у нерезидентов 31% акций за год — это настоящее событие."""
    points = buyback_series([
        (98_094_000, 4_361.5, 284.8),
        (67_871_000, 6_990.0, 864.5),
    ])
    assert buyback_payout(points, 2) is not None
    assert buyback_payout(points, 2) > 100     # раздали больше заработанного


def test_buyback_needs_prices():
    points = [YearPoint(2020 + i, eps=10.0, shares_normalized=1000.0) for i in range(3)]
    assert buyback_payout(points, 3) is None


# ── Уровень по тенденции ───────────────────────────────────────────────────

def line(values, first_year=2019):
    return [YearPoint(first_year + i, eps=v) for i, v in enumerate(values)]


def test_trend_follows_a_rising_series_where_the_average_lags():
    """Средняя занижает растущего — линия тренда нет.

    Ряд 100…160 растёт ровно на 10 в год. Средняя даёт 130, тренд на
    последний год — 160, и это то, что компания зарабатывает сейчас.
    """
    points = line([100, 110, 120, 130, 140, 150, 160])
    assert window_average(points, "eps", 7).value == pytest.approx(130.0)
    trend = trend_value(points, "eps", 7)
    assert trend.value == pytest.approx(160.0)
    assert trend.slope == pytest.approx(10.0)


def test_trend_lowers_a_falling_series_where_the_average_flatters():
    points = line([160, 150, 140, 130, 120, 110, 100])
    assert window_average(points, "eps", 7).value == pytest.approx(130.0)
    assert trend_value(points, "eps", 7).value == pytest.approx(100.0)


def test_flat_series_gives_the_same_answer_both_ways():
    points = line([100] * 7)
    assert trend_value(points, "eps", 7).value == pytest.approx(100.0)
    assert trend_value(points, "eps", 7).slope == pytest.approx(0.0)


def test_trend_is_capped_at_the_peak_already_achieved():
    """Оговорка авторов на с. 568: не брать значения выше уже достигнутых.

    Ряд заканчивается провалом, но линия по нему уходит выше исторического
    максимума. Такая линия — прогноз, а не анализ прошлого.
    """
    points = line([10, 40, 100, 60, 200, 120, 130])
    trend = trend_value(points, "eps", 7)
    assert trend.peak == pytest.approx(200.0)
    assert trend.value <= trend.peak


def test_least_squares_not_endpoints():
    """По крайним точкам ответ скачет вдвое, по регрессии держится.

    Книга показывает это на индексе Value Line: 11,5% против 4,8% при сдвиге
    периода на год. Здесь тот же приём: выброс в середине двигает линию
    заметно слабее, чем сдвинул бы крайнюю точку.
    """
    steady = trend_value(line([100, 110, 120, 130, 140]), "eps", 5)
    with_spike = trend_value(line([100, 110, 500, 130, 140]), "eps", 5)
    assert steady.slope == pytest.approx(10.0)
    # Выброс втрое выше ряда сдвинул наклон, но не перевернул его.
    assert with_spike.slope > 0


def test_two_points_are_not_a_trend():
    """Через две точки проходит ровно одна прямая — тенденцией это не назвать."""
    assert trend_value(line([100, 200]), "eps", 2) is None


def test_trend_needs_data():
    assert trend_value([], "eps", 7) is None
    assert trend_value([YearPoint(2024)], "eps", 7) is None


def test_annual_growth_is_the_slope_relative_to_the_level():
    points = line([100, 110, 120, 130, 140, 150, 160])
    assert trend_value(points, "eps", 7).annual_growth == pytest.approx(6.25, abs=0.01)


def test_trend_rides_along_with_the_estimate():
    """Тренд не заменяет среднюю, а едет рядом: расхождение — сигнал."""
    points = [
        YearPoint(2019 + i, eps=100.0 + 10 * i, roe=15.0, book_value_per_share=700.0)
        for i in range(7)
    ]
    result = analyze(points, with_cash=False).earnings[7]
    assert result.per_share.value == pytest.approx(130.0)
    assert result.trend.value == pytest.approx(160.0)
    assert result.as_dict()["trend"]["annual_growth"] is not None
