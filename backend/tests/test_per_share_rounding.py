"""Округление величин «на акцию».

Два знака — привычка рублёвой бумаги, и на копеечной она обнуляет всё: цену,
справедливую стоимость, опорную. График получал ряд из нулей и рисовал прямую
по нижнему краю. В базе точность уже расширили миграцией; теряться она успевала
на выходе из API.
"""

import pytest

from app.utils.per_share import decimals_for, per_share


@pytest.mark.parametrize("value, expected", [
    (0.0065, 0.0065),        # ТГК-2 — раньше выходил 0.0
    (0.004365, 0.004365),    # ТГК-1
    (0.000762, 0.000762),    # дно ряда ТГК-2
    (0.417, 0.417),          # РусГидро
    (0.01529, 0.0153),
])
def test_a_penny_price_keeps_its_digits(value, expected):
    assert per_share(value) == expected


def test_a_rouble_price_stays_at_two_digits():
    """Лишние знаки у обычной бумаги — шум: 1271,4 остаётся 1271,4."""
    assert per_share(1271.4) == 1271.4
    assert per_share(4072.347) == 4072.35


def test_nothing_is_invented_out_of_an_empty_value():
    assert per_share(None) is None


def test_a_negative_value_is_rounded_by_its_size():
    """Знак на масштаб не влияет: у убыточной компании прибыль на акцию
    бывает и отрицательной, и копеечной одновременно."""
    assert per_share(-0.004365) == -0.004365
    assert per_share(-1271.4) == -1271.4


def test_zero_is_not_a_penny_stock():
    assert per_share(0.0) == 0.0


@pytest.mark.parametrize("value, digits", [
    (5.0, 2), (1.0, 2), (0.99, 4), (0.01, 4), (0.0099, 6), (0.0, 6),
])
def test_the_scale_decides_how_many_digits(value, digits):
    assert decimals_for(value) == digits
