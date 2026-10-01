"""Дневной ряд ключевой ставки: какая ставка действовала и какая средняя."""
from datetime import date, timedelta

import pytest

from app.services.market.key_rate_service import RateSeries


def series(points):
    return RateSeries(sorted(points))


def test_ставка_на_выходной_берётся_с_последнего_рабочего_дня():
    s = series([(date(2015, 1, 30), 17.0), (date(2015, 2, 2), 15.0)])
    assert s.on(date(2015, 1, 31)) == 17.0      # суббота
    assert s.on(date(2015, 2, 2)) == 15.0
    assert s.on(date(2013, 1, 1)) is None       # ставки ещё не было


def test_скользящая_средняя_не_видит_будущего():
    """Средняя на день считается только по дням до него включительно."""
    days = [(date(2015, 1, 1) + timedelta(days=i), 10.0) for i in range(300)]
    days += [(date(2015, 1, 1) + timedelta(days=300 + i), 20.0) for i in range(60)]
    s = series(days)
    before_hike = date(2015, 1, 1) + timedelta(days=299)
    assert s.trailing(before_hike) == pytest.approx(10.0)
    assert s.trailing(before_hike + timedelta(days=30)) > 10.0


def test_короткое_окно_средней_не_даёт():
    """Осень 2013 года, когда ставка только введена, год не описывает."""
    s = series([(date(2013, 9, 13) + timedelta(days=i), 5.5) for i in range(75)])
    assert s.trailing(date(2013, 12, 31)) is None
    assert s.trailing(date(2013, 12, 31), min_days=50) == pytest.approx(5.5)


def test_средняя_за_двенадцать_месяцев_на_конец_года_равна_годовой():
    """Поэтому гейт и график не расходятся: для гейта это одно и то же."""
    days = [(date(2020, 1, 1) + timedelta(days=i), 5.0 + (i % 7)) for i in range(366)]
    s = series(days)
    year_average = sum(r for _, r in days) / len(days)
    assert s.trailing(date(2020, 12, 31), days=365) == pytest.approx(year_average, abs=0.05)
