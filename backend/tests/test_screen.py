"""Пороги поверх осей: своды гл. 14 и гл. 15 с отраслевой поправкой.

Три вещи здесь важнее прочих. Первая — что неизмеримое отделено от провала:
у банка нет текущей ликвидности по устройству бизнеса, и считать это
непрохождением значит завалить сектор формулой. Вторая — что отраслевая
поправка всегда видна: вердикт несёт и применённый порог, и книжный. Третья —
что своды не смешиваются: «20 лет дивидендов» и «платит сейчас» не имеют
середины, и выбирать можно только целиком.
"""

import pytest

from app.services.analysis import screen, screen_axes
from app.services.analysis.screen import (
    DIVIDEND_YEARS,
    FAIL,
    MIN_REVENUE,
    NOT_APPLICABLE,
    PASS,
    PE_PB_PRODUCT,
    STANDARDS,
    UNKNOWN,
    Rule,
)
from app.services.analysis.screen_axes import Axis, Metric
from app.services.analysis.sector_profiles import (
    BANK,
    GRAHAM_DEFAULT,
    RETAIL_GROCERY,
)


def axis(key, label, **metrics):
    """Ось с готовыми величинами — оси считает другой модуль, здесь их дают."""
    return Axis(
        key=key, label=label,
        metrics=tuple(
            Metric(key=name, label=name, value=spec[0],
                   of=spec[1] if len(spec) > 1 else None)
            for name, spec in metrics.items()
        ),
    )


def healthy():
    """Компания, проходящая защитный свод целиком."""
    return [
        axis("profitability", "Рентабельность", roe=(18.0,)),
        axis("size", "Размер", revenue=(900_000.0,)),
        axis("financial", "Финансовое положение", current_ratio=(2.4,)),
        axis("stability", "Стабильность",
             profitable_years=(10.0, 10), profitable_years_short=(5.0, 5)),
        axis("growth", "Рост",
             earnings_growth=(74.0,), earnings_growth_short=(20.0,)),
        axis("dividends", "Дивиденды", streak=(12.0, 15.0)),
        axis("price", "Динамика цен",
             pe_average=(9.0,), pb=(1.1,), pb_tangible=(1.1,), pe_pb=(9.9,)),
    ]


def screened(axes=None, profile=GRAHAM_DEFAULT, standard="defensive"):
    return screen.apply(axes or healthy(), profile, standard, ticker="TEST")


def verdict(result, metric):
    for v in result.verdicts:
        if v.metric == metric:
            return v
    raise AssertionError(f"нет вердикта по {metric}")


# ── Устройство свода ───────────────────────────────────────────────────────

def test_defensive_covers_the_seven_criteria_plus_our_additions():
    """Семь критериев гл. 14, произведение P/E×P/B отдельной строкой, и три
    наших: рентабельность и две по свободному потоку."""
    result = screened()
    assert len(result.verdicts) == 11
    assert {v.axis for v in result.verdicts} == set(screen_axes.AXIS_ORDER)
    ours = {v.metric for v in result.verdicts if v.rule.ours}
    assert ours == {"roe", "revenue", "streak", "cash_positive_years", "cash_growth"}


def test_a_healthy_company_clears_the_defensive_standard():
    result = screened()
    assert result.failed == ()
    assert result.clears is True
    assert result.passed == len(result.checkable)


def test_unknown_standard_is_refused():
    with pytest.raises(ValueError):
        screened(standard="прочее")


def test_both_standards_exist_and_differ():
    assert STANDARDS == ("defensive", "enterprising")
    assert screen.DEFENSIVE != screen.ENTERPRISING


def test_the_screen_refuses_to_produce_a_score():
    """Грэм требует всех критериев сразу — сумма очков это скрыла бы."""
    payload = screened().as_dict()
    assert "score" not in payload
    assert "rank" not in payload


# ── Провал ─────────────────────────────────────────────────────────────────

def test_one_failed_axis_is_enough_to_stop_the_company():
    axes = healthy()
    axes[6] = axis("price", "Динамика цен",
                   pe_average=(21.0,), pb=(1.1,), pe_pb=(23.1,))
    result = screened(axes)
    assert result.clears is False
    assert {v.metric for v in result.failed} == {"pe_average", "pe_pb"}
    assert result.passed == 7


def test_the_product_catches_what_separate_thresholds_let_through():
    """Критерий 7: P/E 14 и P/B 1,45 проходят порознь, произведение — нет."""
    axes = healthy()
    axes[6] = axis("price", "Динамика цен",
                   pe_average=(14.0,), pb=(1.45,), pe_pb=(20.3,))
    assert verdict(screened(axes), "pe_pb").status == PASS

    axes[6] = axis("price", "Динамика цен",
                   pe_average=(14.9,), pb=(1.5,), pe_pb=(22.35,))
    assert verdict(screened(axes), "pe_pb").status == PASS
    assert PE_PB_PRODUCT == 22.5


def test_a_single_loss_year_fails_stability():
    axes = healthy()
    axes[3] = axis("stability", "Стабильность",
                   profitable_years=(9.0, 10), profitable_years_short=(5.0, 5))
    assert verdict(screened(axes), "profitable_years").status == FAIL


# ── Неизмеримое ────────────────────────────────────────────────────────────

def test_missing_data_is_not_a_failure():
    axes = healthy()
    axes[1] = axis("size", "Размер", revenue=(None,))
    result = screened(axes)
    assert verdict(result, "revenue").status == UNKNOWN
    assert result.failed == ()
    assert result.clears is False          # но и прохождением это не считается


def test_an_incomplete_screen_never_clears():
    """Непроверенная ось — не прохождение: Грэм требует всех сразу."""
    axes = healthy()
    axes[5] = axis("dividends", "Дивиденды", streak=(None, None))
    result = screened(axes)
    assert result.complete is False
    assert result.clears is False


def test_a_bank_is_not_failed_for_lacking_current_ratio():
    """Депозиты клиентов — обязательства по природе; это устройство, не риск."""
    axes = healthy()
    axes[2] = axis("financial", "Финансовое положение", current_ratio=(0.05,))
    result = screened(axes, profile=BANK)
    liquidity = verdict(result, "current_ratio")
    assert liquidity.status == NOT_APPLICABLE
    assert "не применяется" in liquidity.reason
    assert liquidity not in result.failed


def test_cash_rules_fail_a_company_whose_profit_looks_fine():
    """Случай Позитива: прибыль ровная, поток отрицателен. Свод, который
    этого не видит, выдаёт такую компанию за устойчивую."""
    axes = healthy()
    axes[3] = axis("stability", "Стабильность",
                   profitable_years=(10.0, 10), profitable_years_short=(5.0, 5),
                   cash_positive_years=(2.0, 10))
    axes[4] = axis("growth", "Рост",
                   earnings_growth=(74.0,), earnings_growth_short=(20.0,),
                   cash_growth=(-40.0,))
    result = screened(axes)
    assert {v.metric for v in result.failed} == {"cash_positive_years", "cash_growth"}
    assert verdict(result, "profitable_years").status == PASS


def test_cash_rule_allows_a_capex_year_but_not_a_decade_of_them():
    """Отрицательный поток в год стройки — вложение, а не убыток."""
    axes = healthy()
    axes[3] = axis("stability", "Стабильность",
                   profitable_years=(10.0, 10), profitable_years_short=(5.0, 5),
                   cash_positive_years=(6.0, 10))
    assert verdict(screened(axes), "cash_positive_years").status == PASS

    axes[3] = axis("stability", "Стабильность",
                   profitable_years=(10.0, 10), profitable_years_short=(5.0, 5),
                   cash_positive_years=(4.0, 10))
    assert verdict(screened(axes), "cash_positive_years").status == FAIL


def test_a_lender_is_not_failed_for_having_no_free_cash_flow():
    """У банка поток клиентских денег к его собственным отношения не имеет,
    и ось его не считает вовсе. Это не пробел, а решённое состояние."""
    result = screened(healthy(), profile=BANK)
    cash = verdict(result, "cash_positive_years")
    assert cash.status == NOT_APPLICABLE
    assert result.unknown == ()
    assert cash not in result.failed


def test_an_implausible_value_is_refused_rather_than_passed():
    """Случай Белуги: испорченная строка прибыли даёт рост +42 868%.
    Засчитать это прохождением хуже, чем признать, что мы не знаем."""
    axes = healthy()
    axes[4] = Axis(
        key="growth", label="Рост",
        metrics=(Metric(key="earnings_growth", label="рост", value=42_868.0,
                        suspect="Прирост 42 868% за десятилетие невозможен"),
                 Metric(key="earnings_growth_short", label="рост", value=18_379.0)),
    )
    result = screened(axes)
    growth = verdict(result, "earnings_growth")
    assert growth.status == UNKNOWN
    assert "невозможен" in growth.reason
    assert result.clears is False


def test_an_inapplicable_axis_is_not_a_gap_in_the_screen():
    """Неприменимость — решённое состояние. Пробел — только нехватка данных."""
    axes = healthy()
    axes[2] = axis("financial", "Финансовое положение", current_ratio=(0.05,))
    result = screened(axes, profile=BANK)
    assert result.unknown == ()
    assert result.complete is True
    assert result.clears is True


def test_size_is_not_required_of_the_enterprising_investor():
    axes = healthy()
    axes[1] = axis("size", "Размер", revenue=(120.0,))
    assert verdict(screened(axes, standard="enterprising"), "revenue").status \
        == NOT_APPLICABLE
    assert verdict(screened(axes), "revenue").status == FAIL


# ── Отраслевая поправка ────────────────────────────────────────────────────

def test_grocery_liquidity_is_judged_by_its_own_band():
    """Низкая ликвидность у продуктовой сети — способ торговать, а не риск."""
    axes = healthy()
    axes[2] = axis("financial", "Финансовое положение", current_ratio=(1.1,))
    assert verdict(screened(axes), "current_ratio").status == FAIL
    assert verdict(screened(axes, profile=RETAIL_GROCERY),
                   "current_ratio").status == PASS


def test_the_book_threshold_stays_visible_next_to_the_applied_one():
    axes = healthy()
    axes[2] = axis("financial", "Финансовое положение", current_ratio=(1.1,))
    adjusted = verdict(screened(axes, profile=RETAIL_GROCERY), "current_ratio")
    assert adjusted.book == 2.0
    assert adjusted.applied == 1.0        # ритейл вдвое мягче промышленности
    assert adjusted.adjusted is True
    assert adjusted.as_dict()["book_text"] == "≥ 2"


def test_the_sector_adjustment_is_relative_so_the_standard_survives():
    """Профиль говорит «во сколько раз», а не «вместо».

    Подстановка абсолютного значения отменяла бы выбор свода: активный
    инвестор получал бы от промышленного профиля ликвидность 2,0 там, где
    книга разрешает 1,5.
    """
    axes = healthy()
    axes[2] = axis("financial", "Финансовое положение", current_ratio=(1.6,))

    strict = verdict(screened(axes), "current_ratio")
    soft = verdict(screened(axes, standard="enterprising"), "current_ratio")
    assert (strict.applied, soft.applied) == (2.0, 1.5)

    grocery = verdict(screened(axes, RETAIL_GROCERY, "enterprising"),
                      "current_ratio")
    assert grocery.applied == 0.75        # 1,5 книжных × половинная отрасль


def test_an_untouched_threshold_is_not_marked_as_adjusted():
    assert verdict(screened(), "pe_pb").adjusted is False


def test_profitability_takes_its_threshold_entirely_from_the_profile():
    """У Грэма порога по рентабельности нет ни в одном своде."""
    roe = verdict(screened(), "roe")
    assert roe.rule.ours is True
    assert roe.book is None
    assert roe.applied == GRAHAM_DEFAULT.bands["roe"].good


# ── Смена свода ────────────────────────────────────────────────────────────

def test_the_enterprising_standard_is_the_softer_one():
    """Компания, не прошедшая защитный свод, может пройти активный."""
    axes = healthy()
    axes[2] = axis("financial", "Финансовое положение", current_ratio=(1.7,))
    axes[5] = axis("dividends", "Дивиденды", streak=(2.0, 5.0))
    axes[1] = axis("size", "Размер", revenue=(3_000.0,))
    assert screened(axes).clears is False
    assert screened(axes, standard="enterprising").clears is True


def test_the_enterprising_standard_is_stricter_on_price():
    """Мягче по качеству, строже по цене — это у Грэма нарочно.

    Защитный инвестор покупает хорошее по справедливой цене, активный —
    дешёвое, и скидку требует больше. P/B 1,3 проходит у первого и не проходит
    у второго; выглядит противоречием, но это две разные сделки.
    """
    axes = healthy()
    axes[6] = axis("price", "Динамика цен",
                   pe_average=(9.0,), pb=(1.3,), pb_tangible=(1.3,),
                   pe_pb=(11.7,))
    assert verdict(screened(axes), "pb").status == PASS
    assert verdict(screened(axes, standard="enterprising"),
                   "pb_tangible").status == FAIL


def test_the_active_standard_is_stricter_on_price_by_design():
    """Не противоречие, а замысел Грэма: защитный инвестор берёт хорошее по
    справедливой цене, активный — дешёвое, и скидку требует больше. Поэтому
    компания может пройти по цене у защитного и не пройти у активного."""
    strict = verdict(screened(standard="defensive"), "pb").applied
    bargain = verdict(screened(standard="enterprising"), "pb_tangible").applied
    assert bargain < strict


def test_dividend_thresholds_have_no_middle_ground():
    axes = healthy()
    axes[5] = axis("dividends", "Дивиденды", streak=(3.0, 8.0))
    assert verdict(screened(axes), "streak").status == FAIL
    assert verdict(screened(axes, standard="enterprising"), "streak").status == PASS


def test_the_dividend_threshold_is_ours_and_says_so():
    streak = verdict(screened(), "streak")
    assert streak.rule.ours is True
    assert "20 лет" in streak.rule.note
    assert DIVIDEND_YEARS == 10


def test_the_size_threshold_is_ours_and_says_so():
    revenue = verdict(screened(), "revenue")
    assert revenue.rule.ours is True
    assert revenue.applied == MIN_REVENUE


# ── Правило само по себе ───────────────────────────────────────────────────

def test_rule_modes():
    low = Rule("a", "m", "min", 10.0, "тест")
    high = Rule("a", "m", "max", 10.0, "тест")
    every = Rule("a", "m", "all", None, "тест")
    assert low.holds(10.0, None) is True and low.holds(9.9, None) is False
    assert high.holds(10.0, None) is True and high.holds(10.1, None) is False
    assert every.holds(10.0, 10) is True and every.holds(9.0, 10) is False
    assert every.holds(9.0, None) is None
    assert low.holds(None, None) is None


def test_rule_text_reads_as_a_threshold():
    assert Rule("a", "m", "min", 2.0, "тест").text() == "≥ 2"
    assert Rule("a", "m", "max", 22.5, "тест").text() == "≤ 22.5"
    assert Rule("a", "m", "all", None, "тест").text() == "без единого убытка"


def test_thresholds_are_written_the_way_people_read_them():
    """Точность здесь мнимая: сами пороги — округлённые суждения."""
    assert Rule("a", "m", "min", 100 / 3, "тест").text() == "≥ 33.3"
    assert Rule("a", "m", "min", 50_000.0, "тест").text() == "≥ 50 000"


def test_small_thresholds_keep_the_digit_that_matters():
    """У порога 0,96 десятая доля — четверть его самого: округлив до единицы,
    мы поменяли бы саму мерку."""
    assert Rule("a", "m", "max", 0.96, "тест").text() == "≤ 0.96"
    assert Rule("a", "m", "max", 8.0, "тест").text() == "≤ 8"


def test_a_criterion_graham_never_set_says_so():
    assert Rule("a", "m", "min", None, "тест", ours=True).text() == "по профилю"


# ── Сериализация ───────────────────────────────────────────────────────────

def test_serialisation_carries_both_thresholds_and_the_source():
    payload = screened().as_dict()
    assert payload["ticker"] == "TEST"
    assert payload["standard_label"].startswith("Защитный")
    assert payload["profile"]["key"] == "industrial"
    row = next(v for v in payload["verdicts"] if v["metric"] == "pe_average")
    assert (row["applied"], row["book"], row["text"]) == (15.0, 15.0, "≤ 15")
    assert row["source"] == "гл. 14, критерий 6"


def test_cash_rescues_a_criterion_that_profit_failed():
    """Случай Лукойла и Новатэка: отчётная прибыль переписана и обвалилась,
    а свободный поток за ту же пятилетку держится. Считать компанию
    сжимающейся по строке отчёта, когда касса говорит другое, значит доверять
    форме отчётности больше, чем деньгам."""
    axes = healthy()
    axes[4] = axis("growth", "Рост",
                   earnings_growth=(74.0,), earnings_growth_short=(-24.5,),
                   cash_growth_short=(18.2,))
    growth = verdict(screened(axes, standard="enterprising"), "earnings_growth_short")
    assert growth.status == PASS
    assert "засчитано по деньгам" in growth.reason


def test_cash_does_not_rescue_when_it_fell_too():
    axes = healthy()
    axes[4] = axis("growth", "Рост",
                   earnings_growth=(74.0,), earnings_growth_short=(-39.5,),
                   cash_growth_short=(-5.2,))
    assert verdict(screened(axes, standard="enterprising"),
                   "earnings_growth_short").status == FAIL


def test_the_defensive_growth_test_has_no_cash_fallback():
    """Запасная величина стоит только у короткого теста: десятилетний тест
    гл. 14 — сам по себе строгий критерий, и смягчать его нечем."""
    assert all(r.alt is None for r in screen.DEFENSIVE)


def test_the_bargain_test_measures_tangible_capital():
    """Гл. 15 меряет цену «чистой стоимостью материальных активов», гл. 14 —
    обычной балансовой. У Грэма это не разнобой: охотнику за дешевизной
    обеспечение нужно твёрдое, а гудвил в ликвидации стоит ноль."""
    axes = healthy()
    axes[6] = axis("price", "Динамика цен",
                   pe_average=(9.0,), pb=(1.1,), pb_tangible=(2.4,),
                   pe_pb=(9.9,))
    assert verdict(screened(axes), "pb").status == PASS
    assert verdict(screened(axes, standard="enterprising"),
                   "pb_tangible").status == FAIL


def test_a_weak_criterion_carries_its_caveat():
    """Пятилетний тест роста считается, но опираться на него в одиночку
    нельзя: окно на российских данных накрывает 2020 и 2022 годы."""
    result = screened(standard="enterprising")
    growth = verdict(result, "earnings_growth_short")
    assert growth.status == PASS
    assert growth.rule.weak is True


def test_only_the_short_growth_test_is_marked_weak():
    weak = {r.metric for r in screen.ENTERPRISING + screen.DEFENSIVE if r.weak}
    assert weak == {"earnings_growth_short"}


def test_a_distorted_value_is_not_counted_as_passed():
    """Случай МТС: отдача 228% формально проходит «≥ 20%», но проходит она
    как измерение структуры капитала, а не прибыльности дела.

    Засчитать такое значит выдать искажение за достижение. Критерий остаётся
    неизмеренным — и компания перестаёт считаться прошедшей.
    """
    axes = healthy()
    axes[0] = Axis(
        key="profitability", label="Рентабельность",
        metrics=(Metric(key="roe", label="Отдача на капитал", value=227.8,
                        suspect="Отдача больше всего капитала"),),
    )
    result = screened(axes)
    roe = verdict(result, "roe")
    assert roe.status == UNKNOWN
    assert result.clears is False
    assert roe not in result.failed        # и провалом это тоже не считается


def test_a_distorted_value_says_so_instead_of_no_data():
    """«Не нашли» и «нашли, но это не то» — разные утверждения, и читателю
    разница существенна."""
    axes = healthy()
    axes[0] = Axis(
        key="profitability", label="Рентабельность",
        metrics=(Metric(key="roe", label="Отдача на капитал", value=227.8,
                        suspect="Отдача больше всего капитала"),),
    )
    distorted = verdict(screened(axes), "roe")
    assert distorted.distorted is True
    assert "Отдача больше" in distorted.reason

    axes[0] = Axis(
        key="profitability", label="Рентабельность",
        metrics=(Metric(key="roe", label="Отдача на капитал", value=None),),
    )
    missing = verdict(screened(axes), "roe")
    assert missing.status == UNKNOWN
    assert missing.distorted is False
    assert missing.reason == "Нет данных"
