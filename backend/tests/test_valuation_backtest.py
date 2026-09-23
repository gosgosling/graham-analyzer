"""Обратный тест оценки: гейт из гл. 4, с. 53.

Главная проверка здесь — на отсутствие заглядывания вперёд. Тест, знающий
будущее, показывает, что модель хорошо объясняет прошлое, зная его исход, то
есть не показывает ничего.
"""

import pytest

from app.services.analysis.valuation_backtest import (
    MIN_BACKTEST_YEARS,
    OFZ_OVER_KEY_RATE,
    BacktestResult,
    BacktestYear,
)


def year(y, price, low=None, high=None, refused=None):
    return BacktestYear(year=y, price=price, low=low, high=high, refused=refused)


# ── Одна точка ─────────────────────────────────────────────────────────────

def test_price_inside_the_band():
    row = year(2020, price=100.0, low=80.0, high=120.0)
    assert row.inside is True
    assert row.distance == pytest.approx(1.0)


def test_price_above_the_band_measures_the_miss():
    row = year(2020, price=150.0, low=80.0, high=120.0)
    assert row.inside is False
    assert row.distance == pytest.approx(1.25)   # 150 / 120


def test_price_below_the_band_measures_the_miss():
    row = year(2020, price=40.0, low=80.0, high=120.0)
    assert row.inside is False
    assert row.distance == pytest.approx(2.0)    # 80 / 40


def test_refused_year_is_not_counted_either_way():
    """Отказ — не промах. Модель не ошиблась, она отказалась говорить."""
    row = year(2020, price=100.0, refused="проценты покрыты 0.9×")
    assert row.inside is None
    assert row.distance is None


# ── Приговор по компании ───────────────────────────────────────────────────

def test_never_hitting_is_the_case_from_the_book():
    """Оценка, ни разу не совпавшая с ценой за цикл, подозрительна."""
    result = BacktestResult("TEST", [
        year(2018 + i, price=200.0, low=80.0, high=120.0) for i in range(6)
    ])
    assert result.hits == 0
    assert result.verdict == "ни разу"


def test_hitting_half_the_time_is_good_enough():
    rows = [year(2018 + i, price=100.0, low=80.0, high=120.0) for i in range(3)]
    rows += [year(2021 + i, price=200.0, low=80.0, high=120.0) for i in range(3)]
    result = BacktestResult("TEST", rows)
    assert result.hit_rate == pytest.approx(0.5)
    assert result.verdict == "часто"


def test_rare_hits_are_named_as_such():
    rows = [year(2018, price=100.0, low=80.0, high=120.0)]
    rows += [year(2019 + i, price=300.0, low=80.0, high=120.0) for i in range(5)]
    result = BacktestResult("TEST", rows)
    assert result.verdict == "изредка"


def test_short_history_gives_no_verdict():
    """На пяти годах можно попасть в одну фазу цикла и принять её за правило."""
    result = BacktestResult("TEST", [
        year(2022 + i, price=200.0, low=80.0, high=120.0) for i in range(3)
    ])
    assert result.verdict == "мало лет"
    assert MIN_BACKTEST_YEARS == 5


def test_refused_years_do_not_pad_the_history():
    rows = [year(2018 + i, price=100.0, refused="нет данных") for i in range(8)]
    rows.append(year(2026, price=100.0, low=80.0, high=120.0))
    result = BacktestResult("TEST", rows)
    assert len(result.counted) == 1
    assert result.verdict == "мало лет"


def test_median_distance_summarises_the_misses():
    rows = [
        year(2018, price=120.0, low=80.0, high=100.0),   # ×1,2
        year(2019, price=140.0, low=80.0, high=100.0),   # ×1,4
        year(2020, price=90.0, low=80.0, high=100.0),    # внутри, ×1,0
    ]
    assert BacktestResult("TEST", rows).median_distance == pytest.approx(1.2)


def test_empty_result_is_harmless():
    result = BacktestResult("TEST", [])
    assert result.hits == 0
    assert result.hit_rate is None
    assert result.median_distance is None
    assert result.verdict == "мало лет"


def test_result_is_serialisable():
    payload = BacktestResult("TEST", [
        year(2018 + i, price=100.0, low=80.0, high=120.0) for i in range(6)
    ]).as_dict()
    assert payload["ticker"] == "TEST"
    assert payload["hits"] == 6
    assert payload["verdict"] == "часто"
    assert payload["years"][0]["inside"] is True


# ── Подстановка ставки ─────────────────────────────────────────────────────

def test_rate_spread_matches_todays_gap():
    """Ключевая 14,98% против ОФЗ 15,7–16,2% на 30.08.2026 — около пункта."""
    assert OFZ_OVER_KEY_RATE == 1.0


# ── Гейт обязан проверять ту модель, которую мы показываем ─────────────────


def test_бэктест_передаёт_в_оценку_всё_то_же_что_и_живой_расчёт():
    """Защита от молчаливого расхождения гейта с показываемой оценкой.

    Ошибка, ради которой тест написан: `value_band` получила два новых
    параметра — наблюдаемый рост и долю искажённых лет, — и живой расчёт их
    передавал, а бэктест нет. Гейт при этом проходил и выглядел исправным,
    только проверял он другую модель: денежная лестница получала нулевой рост
    вместо наблюдаемого, а надбавка за начисления не начислялась вовсе.

    Расхождение такого рода не ловится ни одним тестом на поведение — обе
    стороны по отдельности работают правильно. Поэтому проверяется само
    совпадение наборов аргументов.
    """
    import inspect

    from app.services.analysis import valuation_backtest
    from app.services.analysis.company_valuation import assess, value_band
    from app.services.analysis.valuation_guards import structure

    def named_args(func, callee):
        """Имена аргументов, которые `func` передаёт в вызов `callee(...)`."""
        source = inspect.getsource(func)
        if f"{callee}(" not in source:
            return set()
        tail = source.split(f"{callee}(")[1]
        return {
            line.split("=")[0].strip()
            for line in tail.split("\n")
            if "=" in line and not line.strip().startswith("#")
        }

    for callee, target in (("value_band", value_band), ("structure", structure)):
        accepted = set(inspect.signature(target).parameters)
        live = named_args(assess, callee) & accepted
        back = named_args(valuation_backtest.backtest, callee) & accepted
        assert live - back == set(), (
            f"живой расчёт передаёт в {callee} то, чего нет в бэктесте: "
            f"{sorted(live - back)} — гейт проверяет другую модель"
        )
