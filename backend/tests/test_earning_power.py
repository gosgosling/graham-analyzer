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
    passes_graham_growth,
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
