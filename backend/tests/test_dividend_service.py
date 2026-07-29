"""Непрерывность дивидендов — критерий Грэма №4 в адаптации под РФ.

На этот сервис опирается седьмой экран фазы 2 («семь критериев защитного
инвестора»), а до сих пор он не был покрыт ничем. Главное, что проверяется, —
длина серии считается назад от последней выплаты, а не от текущего года:
компания, платившая с 2010 по 2015 и с тех пор молчащая, не имеет
пятнадцатилетней серии в 2026 году.

База — SQLite в памяти; текущий год берётся из `datetime.now`, поэтому годы в
тестах задаются относительно него.
"""
from __future__ import annotations

from datetime import date, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Company, FinancialReport  # noqa: F401
from app.models.enums import AccountingStandard, PeriodType, ReportSource
from app.services.dividends.dividend_service import (
    calculate_dividend_continuity,
    get_dividend_history,
    update_dividend_start_year,
)

THIS_YEAR = datetime.now().year


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


@pytest.fixture
def company(db) -> Company:
    company = Company(figi="FIGI0001", ticker="TEST", name="Тестовая компания", currency="RUB")
    db.add(company)
    db.commit()
    return company


def _add_year(
    db,
    company: Company,
    year: int,
    *,
    dividends_per_share: float | None = 10.0,
    price_per_share: float | None = 100.0,
) -> FinancialReport:
    """Годовой отчёт: дивиденд задан → считается выплаченным."""
    report = FinancialReport(
        company_id=company.id,
        period_type=PeriodType.ANNUAL,
        fiscal_year=year,
        accounting_standard=AccountingStandard.IFRS,
        consolidated=True,
        report_date=date(year, 12, 31),
        source=ReportSource.MANUAL,
        report_type="general",
        currency="RUB",
        dividends_paid=dividends_per_share is not None,
        dividends_per_share=dividends_per_share,
        price_per_share=price_per_share,
    )
    db.add(report)
    db.commit()
    return report


# ─── Длина серии ─────────────────────────────────────────────────────────────


def test_unbroken_streak_up_to_last_year(db, company):
    """Платили 12 лет подряд и продолжают — серия непрерывна."""
    for year in range(THIS_YEAR - 11, THIS_YEAR + 1):
        _add_year(db, company, year)

    result = calculate_dividend_continuity(db, company.id, min_years=10)

    assert result.years_of_continuous_payments == 12
    assert result.is_continuous is True
    assert result.gap_years == []
    assert result.last_payment_year == THIS_YEAR


def test_streak_is_counted_back_from_the_last_payment(db, company):
    """Выплаты прекратились шесть лет назад — серии «до сегодня» нет.

    Раньше здесь получалось «лет непрерывных выплат» = текущий год минус год
    начала, то есть история засчитывалась как продолжающаяся.
    """
    for year in range(THIS_YEAR - 16, THIS_YEAR - 5):  # 11 лет подряд, конец — 6 лет назад
        _add_year(db, company, year)

    result = calculate_dividend_continuity(db, company.id, min_years=10)

    assert result.years_of_continuous_payments == 11
    assert result.is_continuous is False  # нет свежей выплаты
    assert result.last_payment_year == THIS_YEAR - 6
    assert "прервана" in result.recommendation


def test_gap_shortens_the_streak(db, company):
    """Пропуск в середине обрывает серию: считается только часть после него."""
    for year in (2016, 2017, 2018):
        _add_year(db, company, year)
    for year in range(2020, THIS_YEAR + 1):
        _add_year(db, company, year)

    result = calculate_dividend_continuity(db, company.id, min_years=10)

    assert 2019 in result.gap_years
    assert result.years_of_continuous_payments == THIS_YEAR - 2020 + 1
    assert result.is_continuous is (result.years_of_continuous_payments >= 10)


def test_last_year_payment_still_counts_as_recent(db, company):
    """Дивиденд за прошлый год объявляют в этом — отставание на год допустимо."""
    for year in range(THIS_YEAR - 10, THIS_YEAR):
        _add_year(db, company, year)

    result = calculate_dividend_continuity(db, company.id, min_years=10)

    assert result.years_of_continuous_payments == 10
    assert result.is_continuous is True


def test_short_history_is_not_continuous(db, company):
    for year in range(THIS_YEAR - 2, THIS_YEAR + 1):
        _add_year(db, company, year)

    result = calculate_dividend_continuity(db, company.id, min_years=10)

    assert result.years_of_continuous_payments == 3
    assert result.is_continuous is False
    assert "Недостаточная история" in result.recommendation


def test_company_without_dividends(db, company):
    _add_year(db, company, THIS_YEAR, dividends_per_share=None)

    result = calculate_dividend_continuity(db, company.id)

    assert result.years_of_continuous_payments == 0
    assert result.is_continuous is False
    assert result.last_payment_year is None


def test_unknown_company_raises(db):
    with pytest.raises(ValueError):
        calculate_dividend_continuity(db, company_id=99999)


def test_analyst_start_year_is_used_for_gap_detection(db, company):
    """Год начала выплат, проставленный аналитиком, задаёт окно поиска пропусков.

    В базе есть отчёты только с 2020-го, но аналитик знает, что компания платит
    с 2015-го — значит 2015–2019 попадают в пропуски, а не исчезают.
    """
    company.dividend_start_year = 2015
    db.commit()
    for year in range(2020, THIS_YEAR + 1):
        _add_year(db, company, year)

    result = calculate_dividend_continuity(db, company.id)

    assert result.dividend_start_year == 2015
    assert result.gap_years == list(range(2015, 2020))


# ─── История и год начала выплат ─────────────────────────────────────────────


def test_history_is_newest_first_with_yield(db, company):
    _add_year(db, company, 2024, dividends_per_share=10.0, price_per_share=200.0)
    _add_year(db, company, 2025, dividends_per_share=8.0, price_per_share=100.0)

    history = get_dividend_history(db, company.id)

    assert [row["year"] for row in history] == [2025, 2024]
    assert history[0]["dividend_yield"] == 8.0   # 8 / 100
    assert history[1]["dividend_yield"] == 5.0   # 10 / 200


def test_history_without_price_has_no_yield(db, company):
    _add_year(db, company, 2025, dividends_per_share=8.0, price_per_share=None)

    history = get_dividend_history(db, company.id)

    assert history[0]["dividend_yield"] is None


def test_history_skips_years_without_payments(db, company):
    _add_year(db, company, 2024, dividends_per_share=None)
    _add_year(db, company, 2025, dividends_per_share=8.0)

    assert [row["year"] for row in get_dividend_history(db, company.id)] == [2025]


def test_update_start_year_takes_earliest_payment(db, company):
    _add_year(db, company, 2019, dividends_per_share=None)  # без выплаты — не считается
    _add_year(db, company, 2021)
    _add_year(db, company, 2023)

    assert update_dividend_start_year(db, company.id) == 2021
    assert company.dividend_start_year == 2021


def test_update_start_year_without_payments_returns_none(db, company):
    _add_year(db, company, 2025, dividends_per_share=None)

    assert update_dividend_start_year(db, company.id) is None
    assert company.dividend_start_year is None
