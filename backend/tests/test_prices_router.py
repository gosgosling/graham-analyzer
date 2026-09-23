"""История цены для графика: главное здесь — отсутствие заглядывания вперёд."""

from datetime import date, timedelta

import pytest

from app.routers.prices_router import (
    PUBLICATION_LAG,
    PUBLICATION_MIN_LAG,
    _published_on,
)


class FakeReport:
    def __init__(self, fiscal_year, report_date=None):
        self.fiscal_year = fiscal_year
        self.report_date = report_date


def test_дата_баланса_за_дату_публикации_не_принимается():
    """Поле `report_date` в этой базе — конец периода, а не публикация.

    У 1204 годовых отчётов из 1210 там стоит 31 декабря. Принять это за дату
    публикации значило бы объявить, что рынок знал годовую прибыль тридцать
    первого декабря, — то есть построить кривую множителя на заглядывании
    вперёд длиной в четыре месяца.
    """
    published = _published_on(FakeReport(2024, date(2024, 12, 31)))
    assert published == date(2024, 12, 31) + PUBLICATION_LAG
    assert published > date(2025, 4, 1)


def test_настоящая_дата_публикации_принимается():
    """Там, где дата отстоит от конца периода, она и есть публикация."""
    actual = date(2025, 3, 14)
    assert _published_on(FakeReport(2024, actual)) == actual


def test_граница_доверия_к_дате():
    period_end = date(2024, 12, 31)
    just_under = period_end + PUBLICATION_MIN_LAG - timedelta(days=1)
    just_over = period_end + PUBLICATION_MIN_LAG

    assert _published_on(FakeReport(2024, just_under)) != just_under
    assert _published_on(FakeReport(2024, just_over)) == just_over


def test_без_даты_берётся_срок_раскрытия():
    assert _published_on(FakeReport(2024)) == date(2024, 12, 31) + PUBLICATION_LAG


def test_срок_раскрытия_укладывается_в_норматив():
    """120 дней — предел, установленный правилами раскрытия, а не вкус."""
    assert PUBLICATION_LAG == timedelta(days=120)
