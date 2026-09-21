"""Семь осей главы 13 — величины без порогов.

Главное, что здесь проверяется: модуль не выносит приговоров. Он считает и
отдаёт ряд; всё, что похоже на «прошла / не прошла», должно оставаться за его
пределами. Второе по важности — что деньги не считаются там, где они ничего не
значат: у кредитной организации поток клиентских средств к её собственным
деньгам отношения не имеет.
"""

from datetime import date

import pytest

from app.services.analysis import screen_axes
from app.services.analysis.earning_power import YearPoint
from app.services.analysis.screen_axes import (
    AXIS_ORDER,
    GROWTH_SPAN,
    PRICE_WINDOW,
    STABILITY_SPAN,
    Axis,
    Metric,
)


class FakeMultiplier:
    """Годовой срез кэша — ровно те поля, которые читают оси."""

    FIELDS = (
        "current_ratio", "debt_to_equity", "net_debt_to_fcf", "pb_ratio",
        "dividend_yield", "ltm_revenue", "total_assets", "roe", "equity",
        "net_debt",
    )

    def __init__(self, year, **values):
        self.date = date(year, 12, 31)
        for name in self.FIELDS:
            setattr(self, name, values.get(name))


def points(count=10, first=2015, **overrides):
    """Ровный ряд, который каждый тест портит в нужном ему месте."""
    rows = []
    for i in range(count):
        year = first + i
        rows.append(YearPoint(
            year=year,
            eps=overrides.get("eps", {}).get(year, 100.0 + i * 10),
            fcf_per_share=overrides.get("fcf", {}).get(year, 90.0 + i * 8),
            roe=overrides.get("roe", {}).get(year, 15.0),
            fcf_to_equity=12.0,
            book_value_per_share=overrides.get("bvps", {}).get(year, 600.0),
            dividends_per_share=overrides.get("dps", {}).get(year, 40.0),
            dividends_declared=overrides.get("declared", {}).get(year, True),
            price_normalized=overrides.get("price", {}).get(year, 1200.0),
        ))
    return rows


def mults(count=10, first=2015, **values):
    return {
        first + i: FakeMultiplier(first + i, **values)
        for i in range(count)
    }


# ── Устройство ─────────────────────────────────────────────────────────────

class FakeLive:
    """Свежий срез кэша: последние двенадцать месяцев и сегодняшняя цена."""

    FIELDS = (
        "roe", "pb_ratio", "pe_ratio", "current_ratio", "debt_to_equity",
        "net_debt_to_fcf", "dividend_yield", "ltm_revenue", "ltm_net_income",
        "ltm_core_fcf", "ltm_fcf", "total_assets", "equity", "price_used",
    )

    def __init__(self, **values):
        for name in self.FIELDS:
            setattr(self, name, values.get(name))


# ── Скользящий год ─────────────────────────────────────────────────────────

def test_current_reading_comes_from_the_trailing_year():
    """Случай Лукойла: за календарный 2025 год отдача 10,5%, за скользящий 17,3."""
    axis = screen_axes.profitability(
        points(), mults(roe=10.5), {}, is_lender=False, live=FakeLive(roe=17.3),
    )
    roe = axis.metric("roe")
    assert roe.value == pytest.approx(17.3)
    assert roe.asof == "LTM"


def test_averages_stay_calendar_even_with_a_trailing_year():
    """Скользящий год перекрывается с последним календарным: в среднюю его
    подмешивать нельзя, иначе год посчитается дважды."""
    axis = screen_axes.profitability(
        points(), mults(), {}, is_lender=False, live=FakeLive(roe=17.3),
    )
    roe = axis.metric("roe")
    assert roe.value == pytest.approx(17.3)
    assert roe.average == pytest.approx(15.0)
    assert roe.series[-1] == (2024, 15.0)


def test_price_axis_uses_todays_price_over_last_year_close():
    """Числитель — сегодняшняя цена, знаменатель — средняя за три года."""
    stale = screen_axes.price_level(points(), mults(pb_ratio=1.03))
    fresh = screen_axes.price_level(
        points(), mults(pb_ratio=1.03), live=FakeLive(price_used=900.0, pb_ratio=0.82),
    )
    assert stale.metric("pe_average").value == pytest.approx(1200 / 180)
    assert fresh.metric("pe_average").value == pytest.approx(900 / 180)
    assert fresh.metric("pe_average").asof == "LTM"
    assert fresh.metric("pb").value == pytest.approx(0.82)


def test_without_a_trailing_slice_the_last_year_is_labelled_by_its_year():
    axis = screen_axes.financial_position(mults(current_ratio=0.92), {}, is_lender=False)
    assert axis.metric("current_ratio").asof == "2024"


def test_trailing_cash_return_prefers_the_flow_without_client_money():
    live = FakeLive(ltm_core_fcf=120.0, ltm_fcf=999.0, equity=1000.0)
    axis = screen_axes.profitability(points(), mults(), {}, is_lender=False, live=live)
    assert axis.metric("fcf_to_equity").value == pytest.approx(12.0)


# ── Сторона нуля ───────────────────────────────────────────────────────────

def test_tone_marks_the_side_of_zero_not_a_threshold():
    axis = screen_axes.profitability(points(roe={2024: -4.0}), mults(), {},
                                     is_lender=False)
    assert axis.metric("roe").tone == "bad"

    axis = screen_axes.profitability(points(), mults(), {}, is_lender=False)
    assert axis.metric("roe").tone == "good"


def test_net_cash_position_reads_as_good():
    """Случай Лукойла: чистый долг отрицателен — денег больше, чем займов."""
    axis = screen_axes.financial_position(
        mults(net_debt_to_fcf=-0.46, net_debt=-378_949.0), {}, is_lender=False,
    )
    assert axis.metric("net_debt_to_fcf").tone == "good"
    assert axis.metric("current_ratio").tone is None  # у ликвидности знак нем


def test_a_negative_ratio_from_a_negative_flow_reads_as_bad():
    """Случай Аэрофлота: долг +537 млрд, поток −128 млрд, отношение −4,19.

    Тот же минус, что у Лукойла, и означает он противоположное: долг не
    гасится вовсе. Красить их одним цветом — прямая ошибка, и решает её знак
    числителя, а не знак дроби.
    """
    axis = screen_axes.financial_position(
        mults(net_debt_to_fcf=-4.19, net_debt=537_075.0), {}, is_lender=False,
    )
    debt = axis.metric("net_debt_to_fcf")
    assert debt.tone == "bad"
    assert "не гасится" in debt.note


def test_a_positive_ratio_gets_no_colour():
    """«Два года потока на погашение» и «двенадцать» — разница в пороге, а не
    в знаке, и порога здесь нет."""
    axis = screen_axes.financial_position(
        mults(net_debt_to_fcf=3.2, net_debt=400_000.0), {}, is_lender=False,
    )
    assert axis.metric("net_debt_to_fcf").tone is None


def test_a_full_count_reads_as_good_and_a_broken_one_as_bad():
    axis = screen_axes.stability(points(eps={2017: -50.0}), is_lender=False)
    assert axis.metric("profitable_years").tone == "bad"       # 9 из 10
    assert axis.metric("profitable_years_short").tone == "good"  # 5 из 5


def test_metric_without_value_is_not_known():
    assert Metric(key="x", label="X", value=None).known is False
    assert Metric(key="x", label="X", value=0.0).known is True


def test_axis_finds_its_lead():
    axis = Axis(
        key="a", label="A", lead="second",
        metrics=(Metric(key="first", label="1", value=1.0),
                 Metric(key="second", label="2", value=2.0)),
    )
    assert axis.lead_metric.value == 2.0
    assert axis.metric("нет такой") is None


def test_axis_without_any_value_is_not_measurable():
    """Пустая ось — нехватка данных, а не провал. Приговор ей выносить нельзя."""
    axis = Axis(key="a", label="A", metrics=(Metric(key="x", label="X", value=None),))
    assert axis.measurable is False


def test_build_returns_all_seven_in_the_order_of_chapter_13():
    axes = screen_axes.build(points(), mults(), {})
    assert [a.key for a in axes] == list(AXIS_ORDER)
    assert len(AXIS_ORDER) == 7


def test_no_axis_carries_a_verdict():
    """Модуль не знает порогов — в выдаче не должно быть ничего похожего."""
    payload = screen_axes.as_dict(screen_axes.build(points(), mults(), {}))
    forbidden = {"status", "passed", "verdict", "threshold", "good", "bad"}
    for axis in payload.values():
        assert forbidden.isdisjoint(axis)
        for metric in axis["metrics"]:
            assert forbidden.isdisjoint(metric)


# ── Рентабельность ─────────────────────────────────────────────────────────

def test_profitability_carries_level_and_average():
    axis = screen_axes.profitability(points(), mults(), {}, is_lender=False)
    roe = axis.metric("roe")
    assert roe.value == pytest.approx(15.0)
    assert roe.average == pytest.approx(15.0)
    assert len(roe.series) == 10


def test_profitability_drops_cash_return_for_a_lender():
    axis = screen_axes.profitability(points(), mults(), {}, is_lender=True)
    assert axis.metric("fcf_to_equity") is None
    assert axis.metric("roe") is not None


def test_average_is_refused_when_the_series_crosses_zero():
    """Капитал ушёл в минус — средняя отдача собралась бы из отрицательных
    знаменателей и не значила бы ничего."""
    axis = screen_axes.profitability(
        points(roe={2018: -40.0, 2019: -12.0}), mults(), {}, is_lender=False,
    )
    roe = axis.metric("roe")
    assert roe.average is None
    assert "пересекает ноль" in roe.note


def test_year_uses_cleaned_profit_while_the_average_uses_reported():
    """Правило то же, что для P/E: год — очищенная прибыль, средняя — отчётная."""
    axis = screen_axes.profitability(points(), mults(roe=10.5), {}, is_lender=False)
    roe = axis.metric("roe")
    assert roe.value == pytest.approx(10.5)      # из кэша, очищенная
    assert roe.average == pytest.approx(15.0)    # из ряда, отчётная
    assert "очищенн" in roe.note


def test_without_a_cached_value_the_year_falls_back_to_reported():
    axis = screen_axes.profitability(points(), mults(), {}, is_lender=False)
    assert axis.metric("roe").value == pytest.approx(15.0)


def test_return_that_grew_on_a_shrinking_denominator_is_flagged_amber():
    """Случай Новабев: отдача поднялась на выкупе и выплатах, а не на прибыли.

    Величина верна, и красным её красить не за что. Но и зелёным нельзя:
    отношение выросло с той стороны дроби, с которой рост ничего не значит.
    """
    shrunk = mults()
    shrunk[2023].equity = 26_682.0
    shrunk[2024].equity = 21_870.0          # −18% за год
    axis = screen_axes.profitability(
        points(roe={2023: 17.2, 2024: 23.6}), shrunk, {}, is_lender=False,
    )
    roe = axis.metric("roe")
    assert roe.tone == "warn"
    assert "уменьшении капитала" in roe.note


def test_a_steady_denominator_leaves_the_return_green():
    steady = mults()
    steady[2023].equity = 26_682.0
    steady[2024].equity = 27_100.0
    axis = screen_axes.profitability(
        points(roe={2023: 17.2, 2024: 23.6}), steady, {}, is_lender=False,
    )
    assert axis.metric("roe").tone == "good"


def test_a_falling_return_is_not_blamed_on_the_denominator():
    """Капитал ужался, но и отдача упала — механики роста здесь нет."""
    shrunk = mults()
    shrunk[2023].equity = 26_682.0
    shrunk[2024].equity = 21_870.0
    axis = screen_axes.profitability(
        points(roe={2023: 23.6, 2024: 17.2}), shrunk, {}, is_lender=False,
    )
    assert axis.metric("roe").tone == "good"


def test_negative_equity_beats_the_cleaned_value():
    """Очищенная прибыль не спасает: делить на отрицательный капитал нельзя."""
    # Провал в середине ряда: последний год здоров, величина за него берётся.
    healthy_now = screen_axes.profitability(
        points(bvps={2020: -600.0}), mults(roe=10.5), {}, is_lender=False,
    )
    assert healthy_now.metric("roe").value == pytest.approx(10.5)

    # Капитал отрицателен в последнем году — считать нечего ни по какой прибыли.
    broken_now = screen_axes.profitability(
        points(bvps={y: -600.0 for y in (2023, 2024)}), mults(roe=10.5),
        {}, is_lender=False,
    )
    assert broken_now.metric("roe").value is None


def test_negative_equity_turns_a_loss_into_a_return():
    """Случай Озона: убыток на отрицательном капитале даёт положительную
    «отдачу», и ряд при этом ноль не пересекает."""
    negative = {y: -600.0 for y in (2022, 2023, 2024)}
    axis = screen_axes.profitability(
        points(roe={2022: 349.5, 2023: 64.1, 2024: 0.63}, bvps=negative),
        mults(), {}, is_lender=False,
    )
    roe = axis.metric("roe")
    assert roe.value is None
    assert roe.average is None
    assert roe.flagged == (2022, 2023, 2024)
    assert "Капитал отрицателен с 2022" in roe.note


def test_years_with_negative_equity_are_dropped_but_the_level_survives():
    """Капитал уходил в минус в середине, последний год здоров — считаем."""
    axis = screen_axes.profitability(
        points(bvps={2017: -100.0}), mults(), {}, is_lender=False,
    )
    roe = axis.metric("roe")
    assert roe.value == pytest.approx(15.0)
    assert roe.flagged == (2017,)
    assert "2017" in roe.note
    assert all(year != 2017 for year, _ in roe.series)


def test_return_on_assets_is_marked_undecided():
    axis = screen_axes.profitability(points(), mults(), {}, is_lender=False)
    assert "под вопросом" in axis.metric("roa").note.lower()


# ── Стабильность ───────────────────────────────────────────────────────────

def test_stability_counts_years_without_a_loss():
    axis = screen_axes.stability(points(), is_lender=False)
    profit = axis.metric("profitable_years")
    assert (profit.value, profit.of) == (10.0, 10)
    assert profit.flagged == ()


def test_stability_names_the_losing_years():
    axis = screen_axes.stability(
        points(eps={2017: -50.0, 2021: -10.0}), is_lender=False,
    )
    profit = axis.metric("profitable_years")
    assert (profit.value, profit.of) == (8.0, 10)
    assert profit.flagged == (2017, 2021)


def test_cash_and_profit_may_disagree():
    """Прибыль ровная, поток проваливается — ось помечается, но не валится."""
    axis = screen_axes.stability(points(fcf={2016: -20.0, 2020: -5.0}), is_lender=False)
    assert axis.metric("profitable_years").value == 10.0
    assert axis.metric("cash_positive_years").flagged == (2016, 2020)
    assert axis.lead == "profitable_years"


def test_stability_ignores_cash_for_a_lender():
    axis = screen_axes.stability(points(), is_lender=True)
    assert axis.metric("cash_positive_years") is None


def test_stability_window_is_calendar_not_row_count():
    """Пятнадцать лет истории — смотрим последние десять, ранние убытки вне окна."""
    rows = points(count=15, first=2010, eps={2010: -100.0, 2011: -100.0})
    axis = screen_axes.stability(rows, is_lender=False)
    profit = axis.metric("profitable_years")
    assert profit.of == STABILITY_SPAN
    assert profit.flagged == ()


def test_both_stability_horizons_are_measured():
    """«Нет убытков за десять лет» и «за пять» — разные утверждения."""
    axis = screen_axes.stability(points(eps={2017: -50.0}), is_lender=False)
    assert axis.metric("profitable_years").value == 9.0
    assert axis.metric("profitable_years").of == STABILITY_SPAN
    short = axis.metric("profitable_years_short")
    assert (short.value, short.of) == (5.0, 5)   # убыток 2017 вне пятилетки


def test_stability_denominator_shows_short_history():
    axis = screen_axes.stability(points(count=4, first=2021), is_lender=False)
    assert axis.metric("profitable_years").of == 4


# ── Рост ───────────────────────────────────────────────────────────────────

def test_growth_measures_two_smoothed_ends_of_the_decade():
    """Прибыль 100…190: тройки дают 110 против 180, прирост 63,6%."""
    axis = screen_axes.growth(points(), is_lender=False)
    assert axis.metric("earnings_growth").value == pytest.approx(63.636, abs=0.01)
    assert GROWTH_SPAN == 10


def test_short_growth_smooths_both_ends():
    """Гл. 15 сравнивает два одиночных года, но одиночный год отдаёт ответ
    случайностям этого года. Ряд 140…190: пары 140/150 против 180/190,
    то есть 145 → 185, прирост 27,6%."""
    axis = screen_axes.growth(points(), is_lender=False)
    assert axis.metric("earnings_growth_short").value == pytest.approx(27.586, abs=0.01)


def test_five_years_ago_means_six_calendar_points():
    """Ошибка на единицу, которая переворачивала ответ.

    «Выше, чем пять лет назад» — это 2025 против 2020, а не против 2021. Окно
    ровно в пять лет оставляет между концами четыре года и выбрасывает тот
    самый год, с которым велено сравнивать.
    """
    assert screen_axes.GROWTH_SPAN_SHORT == screen_axes.GROWTH_YEARS_BACK_SHORT + 1

    direction = screen_axes.graham_growth(
        points(), "eps",
        span=screen_axes.GROWTH_SPAN_SHORT,
        smooth=screen_axes.GROWTH_SMOOTH_SHORT,
    )
    assert direction.newer_years[-1] - direction.older_years[0] == 5


def test_smoothing_survives_a_single_restated_year():
    """Случай Лукойла: прибыль за последний год переписана по продолжающейся
    деятельности. Одиночные годы дали бы обвал, пары — умеренное падение."""
    restated = points(count=6, first=2020, eps={
        2020: 1189.0, 2021: 1140.0, 2022: 1668.0, 2023: 1252.0,
        2024: 1252.0, 2025: 158.0,
    })
    short = screen_axes.growth(restated, is_lender=False).metric("earnings_growth_short")
    single = screen_axes._growth_percent(restated, "eps", 5, 1)
    assert single < -80          # 2021 против 2025 — обвал вчетверо
    assert -60 < short.value < -20


def test_growth_is_silent_when_the_decade_is_too_short():
    axis = screen_axes.growth(points(count=4, first=2021), is_lender=False)
    assert axis.metric("earnings_growth").value is None


def test_growth_drops_cash_for_a_lender():
    assert screen_axes.growth(points(), is_lender=True).metric("cash_growth") is None


# ── Финансовое положение ───────────────────────────────────────────────────

def test_financial_position_carries_three_metrics():
    axis = screen_axes.financial_position(
        mults(current_ratio=0.94, debt_to_equity=0.08, net_debt_to_fcf=-0.4),
        {}, is_lender=False,
    )
    assert axis.metric("current_ratio").value == pytest.approx(0.94)
    assert axis.metric("debt_to_equity").value == pytest.approx(0.08)
    assert axis.metric("net_debt_to_fcf").value == pytest.approx(-0.4)
    assert axis.lead == "current_ratio"


def test_liquidity_and_debt_may_point_opposite_ways():
    """Ликвидность провалена, долга нет — ровно то, что теряет одна цифра."""
    axis = screen_axes.financial_position(
        mults(current_ratio=0.94, debt_to_equity=0.08, net_debt_to_fcf=-0.4),
        {}, is_lender=False,
    )
    assert axis.metric("current_ratio").value < 1
    assert axis.metric("net_debt_to_fcf").value < 0


class FakeReport:
    def __init__(self, adequacy):
        self.capital_adequacy_ratio = adequacy


def test_lender_gets_capital_adequacy_instead():
    axis = screen_axes.financial_position(
        mults(current_ratio=0.05),
        {2023: FakeReport(12.4), 2024: FakeReport(13.1)},
        is_lender=True,
    )
    assert axis.metric("current_ratio") is None
    assert axis.metric("capital_adequacy").value == pytest.approx(13.1)
    assert "неприменим" in axis.note


def test_lender_without_adequacy_is_simply_unmeasurable():
    axis = screen_axes.financial_position(mults(), {}, is_lender=True)
    assert axis.measurable is False


# ── Дивиденды ──────────────────────────────────────────────────────────────

def test_dividend_streak_counts_back_from_the_last_year():
    axis = screen_axes.dividends(points(), mults(dividend_yield=12.4))
    streak = axis.metric("streak")
    assert (streak.value, streak.of) == (10.0, 10.0)


def test_streak_breaks_on_a_missed_year():
    """Пропуск в середине обрывает серию — она непрерывная, а не суммарная."""
    axis = screen_axes.dividends(
        points(dps={2019: 0.0}, declared={2019: False}), mults(),
    )
    assert axis.metric("streak").value == 5.0
    assert axis.metric("streak").of == 10.0


def test_total_paid_years_survive_a_broken_streak():
    """Случай Норникеля: платил годами, последние два пропустил. Серия — ноль,
    но объявить его никогда не платившим нельзя."""
    skipped = {2024: 0.0, 2025: 0.0}
    axis = screen_axes.dividends(
        points(count=11, first=2015, dps=skipped, declared={2024: False, 2025: False}),
        mults(),
    )
    assert axis.metric("streak").value == 0.0
    assert axis.metric("paid_years").value == 9.0
    assert axis.metric("paid_years").of == 11.0


def test_declared_without_an_amount_still_counts_as_paid():
    """«Не записали» — не то же самое, что «не платит»."""
    axis = screen_axes.dividends(
        points(dps={2023: None, 2024: None}), mults(),
    )
    assert axis.metric("streak").value == 10.0


def test_dividend_yield_comes_with_its_history():
    axis = screen_axes.dividends(points(), mults(dividend_yield=12.4))
    dy = axis.metric("dividend_yield")
    assert dy.value == pytest.approx(12.4)
    assert dy.average == pytest.approx(12.4)
    assert len(dy.series) == 10


# ── Динамика цен ───────────────────────────────────────────────────────────

def test_pe_uses_the_three_year_average_of_reported_profit():
    """Цена 1200 против средней прибыли 170/180/190 = 180 → P/E 6,67."""
    axis = screen_axes.price_level(points(), mults(pb_ratio=0.66))
    assert axis.metric("pe_average").value == pytest.approx(1200 / 180)
    assert PRICE_WINDOW == 3


def test_product_of_pe_and_pb_is_the_seventh_criterion():
    axis = screen_axes.price_level(points(), mults(pb_ratio=0.66))
    pe = axis.metric("pe_average").value
    assert axis.metric("pe_pb").value == pytest.approx(pe * 0.66)


def test_price_axis_stays_silent_on_losses():
    losses = {year: -10.0 for year in (2022, 2023, 2024)}
    axis = screen_axes.price_level(points(eps=losses), mults(pb_ratio=0.66))
    assert axis.metric("pe_average").value is None
    assert axis.metric("pe_pb").value is None


# ── Размер ─────────────────────────────────────────────────────────────────

def test_size_reads_the_latest_revenue():
    axis = screen_axes.size(mults(ltm_revenue=8_600_000.0))
    assert axis.metric("revenue").value == pytest.approx(8_600_000.0)


# ── Пустая база ────────────────────────────────────────────────────────────

def test_no_history_produces_axes_that_admit_it():
    axes = screen_axes.build([], {}, {})
    assert [a.key for a in axes] == list(AXIS_ORDER)
    assert all(not a.measurable for a in axes if a.key != "dividends")


def test_serialisation_keeps_the_series():
    payload = screen_axes.as_dict(screen_axes.build(points(), mults(pb_ratio=0.7), {}))
    roe = payload["profitability"]["metrics"][0]
    assert roe["series"][0] == [2015, 15.0]
    assert payload["stability"]["lead"] == "profitable_years"


# ── Правдоподобие роста ────────────────────────────────────────────────────

def test_a_real_multibagger_is_not_called_corrupted():
    """Случай Новабев: +1 122% за десятилетие при совершенно чистом ряде.

    Прибыль выросла с 275 млн до 5 169 млн, выручка с 35,9 до 149,3 млрд —
    рост настоящий, просто база 2016 года лежит в яме 2015-го. Порог по
    итоговым процентам объявлял такую компанию испорченной строкой, то есть
    врал о её данных.
    """
    assert screen_axes._implausible(1122.2, gap=7) is None


def test_a_rate_no_company_holds_is_still_caught():
    """Ради чего проверка заводилась: +42 868% за десятилетие — это около
    90% в год десять лет подряд."""
    note = screen_axes._implausible(42_868.0, gap=10)
    assert note is not None
    assert "в год" in note


def test_plausibility_is_judged_per_year_not_per_window():
    """Годовой темп сопоставим между окнами разной длины, итоговый — нет.
    Одни и те же +1 122% за семь лет обычны, а за два года невозможны."""
    assert screen_axes._implausible(1122.2, gap=7) is None
    assert screen_axes._implausible(1122.2, gap=2) is not None


def test_falling_series_and_missing_gap_are_left_alone():
    assert screen_axes._implausible(-90.0, gap=10) is None
    assert screen_axes._implausible(5000.0, gap=None) is None
    assert screen_axes._implausible(None, gap=10) is None


# ── Знаменатель отдачи ─────────────────────────────────────────────────────

def test_a_return_above_the_whole_capital_is_flagged():
    """Случай МТС: капитал ходит вокруг нуля, и отдача выходит 228%, 440%,
    3 228%. Ни одно из этих чисел не описывает бизнес — они описывают
    структуру капитала. Тем же порогом таблица мультипликаторов пишет
    «Искажено»."""
    axis = screen_axes.profitability(
        points(roe={2024: 227.8}), mults(), {}, is_lender=False,
    )
    roe = axis.metric("roe")
    assert roe.tone == "warn"
    assert "структуру капитала" in roe.note
    # И сравнивать её с порогом нельзя: 228% формально проходят «≥ 20%».
    assert roe.suspect is not None


def test_a_hugely_negative_return_is_flagged_too():
    """−924% у той же компании — тот же крошечный знаменатель, только капитал
    ушёл в минус. Красить это просто «плохо» значит утверждать, что бизнес
    потерял девять капиталов за год."""
    axis = screen_axes.profitability(
        points(roe={2024: -924.4}), mults(), {}, is_lender=False,
    )
    assert axis.metric("roe").tone == "warn"


def test_an_ordinary_return_keeps_its_sign_colour():
    assert screen_axes.profitability(
        points(), mults(), {}, is_lender=False,
    ).metric("roe").tone == "good"
    assert screen_axes.profitability(
        points(roe={2024: -4.0}), mults(), {}, is_lender=False,
    ).metric("roe").tone == "bad"


def test_the_tiny_denominator_outranks_the_shrinking_one():
    """Обе причины разом — говорим о сильной: базы для отношения просто нет."""
    shrunk = mults()
    shrunk[2023].equity = 26_682.0
    shrunk[2024].equity = 1_720.0
    axis = screen_axes.profitability(
        points(roe={2023: 17.2, 2024: 3228.4}), shrunk, {}, is_lender=False,
    )
    assert "структуру капитала" in axis.metric("roe").note


def test_the_cash_return_gets_the_same_caveat():
    """Свободный поток к капиталу делится на тот же капитал: у МТС 788%."""
    axis = screen_axes.profitability(
        points(), mults(), {}, is_lender=False,
        live=FakeLive(ltm_core_fcf=7875.0, equity=1000.0),
    )
    cash = axis.metric("fcf_to_equity")
    assert cash.tone == "warn"
    assert "структуру капитала" in cash.note
    assert cash.suspect is not None


# ── Скользящий год у банка ─────────────────────────────────────────────────

def test_bank_metrics_prefer_the_trailing_year():
    """Случай Сбера: доля проблемных за 2025 год 4,82%, за скользящий 5,42%.

    Рядом на той же строке стояли издержки к доходам с пометкой LTM — два
    числа на разные даты, и сказано об этом было только про одно.
    """
    reports = {2024: FakeReport(12.0), 2025: FakeReport(11.7)}
    axis = screen_axes.financial_position(
        mults(), reports, is_lender=True,
        ltm_bank={"npl_ratio": 5.42, "capital_adequacy_core": 12.0},
    )
    npl = axis.metric("npl_ratio")
    assert npl.value == pytest.approx(5.42)
    assert npl.asof == "LTM"


def test_without_a_trailing_slice_the_bank_falls_back_to_the_report():
    axis = screen_axes.financial_position(
        mults(), {2025: FakeReport(11.7)}, is_lender=True, ltm_bank=None,
    )
    assert axis.metric("capital_adequacy").value == pytest.approx(11.7)
    assert axis.metric("capital_adequacy").asof == "2025"


def test_the_cycle_average_stays_on_annual_years():
    """Среднюю за цикл скользящим годом не портим: последний год посчитался
    бы дважды. А вот пик берём с его учётом — свежее ухудшение важно."""
    axis = screen_axes.stability(
        points(), is_lender=True, reports={}, ltm_bank={"cost_of_risk": 9.9},
    )
    assert axis.metric("cost_of_risk_average") is None   # нет годовых — нет средней
