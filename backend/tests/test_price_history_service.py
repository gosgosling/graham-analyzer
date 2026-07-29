"""Бэкфилл истории цен: какой диапазон запрашивается и что попадает в базу.

Сервис вызывается при старте сервера и по расписанию, то есть ошибка здесь
тихо портит цены сразу у всех компаний — а от цен зависят P/E, запас прочности
и график фазы 2. MOEX подменяется: тесты не ходят в сеть.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import List, Tuple

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Company, FinancialReport, StockPrice  # noqa: F401
from app.models.enums import AccountingStandard, PeriodType, ReportSource
from app.services.market import price_history_service
from app.services.market.price_history_service import (
    backfill_all_companies,
    backfill_company_prices,
)

TODAY = date.today()
YESTERDAY = TODAY - timedelta(days=1)


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


@pytest.fixture
def moex(monkeypatch):
    """Заглушка MOEX: пишет запрошенные диапазоны, отдаёт заданный ответ."""

    class FakeMoex:
        def __init__(self) -> None:
            self.calls: List[Tuple[str, date, date]] = []
            self.rows: List[Tuple[date, float]] = []
            self.raises_for: set[str] = set()

        def __call__(self, ticker: str, from_date: date, till_date: date):
            self.calls.append((ticker, from_date, till_date))
            if ticker in self.raises_for:
                raise RuntimeError("MOEX недоступен")
            return list(self.rows)

    fake = FakeMoex()
    monkeypatch.setattr(price_history_service, "get_price_history", fake)
    return fake


def _report(db, company: Company, report_date: date) -> FinancialReport:
    report = FinancialReport(
        company_id=company.id,
        period_type=PeriodType.ANNUAL,
        fiscal_year=report_date.year,
        accounting_standard=AccountingStandard.IFRS,
        consolidated=True,
        report_date=report_date,
        source=ReportSource.MANUAL,
        report_type="general",
        currency="RUB",
    )
    db.add(report)
    db.commit()
    return report


def _stored(db, company_id: int) -> List[Tuple[date, float]]:
    rows = (
        db.query(StockPrice)
        .filter(StockPrice.company_id == company_id)
        .order_by(StockPrice.date)
        .all()
    )
    return [(row.date, float(row.price)) for row in rows]


# ─── Когда бэкфилл не нужен ──────────────────────────────────────────────────


def test_company_without_reports_is_skipped(db, company, moex):
    """Нет отчётов — нет точки отсчёта: в MOEX даже не ходим."""
    assert backfill_company_prices(db, company) == 0
    assert moex.calls == []


def test_up_to_date_company_is_not_requested_again(db, company, moex):
    """Последняя запись за вчера — цены актуальны."""
    _report(db, company, TODAY - timedelta(days=30))
    db.add(StockPrice(company_id=company.id, date=YESTERDAY, price=100.0, source="moex"))
    db.commit()

    assert backfill_company_prices(db, company) == 0
    assert moex.calls == []


def test_moex_without_data_adds_nothing(db, company, moex):
    _report(db, company, TODAY - timedelta(days=10))
    moex.rows = []

    assert backfill_company_prices(db, company) == 0
    assert _stored(db, company.id) == []


def test_range_starting_after_yesterday_is_not_requested(db, company, moex):
    """Отчёт с датой в будущем не должен вызывать запрос назад во времени."""
    _report(db, company, TODAY + timedelta(days=5))

    assert backfill_company_prices(db, company) == 0
    assert moex.calls == []


# ─── Диапазон запроса ────────────────────────────────────────────────────────


def test_first_backfill_starts_from_earliest_report(db, company, moex):
    """Точка отсчёта — самый ранний отчёт, конец диапазона — вчера."""
    earliest = TODAY - timedelta(days=20)
    _report(db, company, earliest)
    _report(db, company, TODAY - timedelta(days=5))
    moex.rows = [(earliest, 100.0), (earliest + timedelta(days=1), 101.5)]

    added = backfill_company_prices(db, company)

    assert added == 2
    assert moex.calls == [("TEST", earliest, YESTERDAY)]
    assert _stored(db, company.id) == [(earliest, 100.0), (earliest + timedelta(days=1), 101.5)]


def test_incremental_backfill_continues_from_next_day(db, company, moex):
    """Уже есть цены до какой-то даты — запрашиваем со следующего дня."""
    _report(db, company, TODAY - timedelta(days=30))
    last_stored = TODAY - timedelta(days=10)
    db.add(StockPrice(company_id=company.id, date=last_stored, price=90.0, source="moex"))
    db.commit()
    moex.rows = [(last_stored + timedelta(days=1), 91.0)]

    added = backfill_company_prices(db, company)

    assert added == 1
    assert moex.calls == [("TEST", last_stored + timedelta(days=1), YESTERDAY)]


def test_force_from_overrides_stored_history(db, company, moex):
    """Ручной запрос перекачивает диапазон, даже если данные уже есть."""
    _report(db, company, TODAY - timedelta(days=30))
    db.add(StockPrice(company_id=company.id, date=YESTERDAY, price=100.0, source="moex"))
    db.commit()
    forced_from = TODAY - timedelta(days=3)
    moex.rows = [(forced_from, 95.0)]

    added = backfill_company_prices(db, company, force_from=forced_from)

    assert added == 1
    assert moex.calls == [("TEST", forced_from, YESTERDAY)]


# ─── Идемпотентность ─────────────────────────────────────────────────────────


def test_existing_day_is_not_duplicated(db, company, moex):
    """MOEX вернул день, который уже сохранён — второй записи не появится."""
    earliest = TODAY - timedelta(days=5)
    _report(db, company, earliest)
    moex.rows = [(earliest, 100.0), (earliest + timedelta(days=1), 101.0)]
    backfill_company_prices(db, company)

    added = backfill_company_prices(db, company, force_from=earliest)

    assert added == 0
    assert len(_stored(db, company.id)) == 2


# ─── Бэкфилл по всем компаниям ───────────────────────────────────────────────


def test_backfill_all_reports_only_companies_with_new_prices(db, company, moex):
    """В сводку попадают только те, кому реально что-то докачали."""
    earliest = TODAY - timedelta(days=5)
    _report(db, company, earliest)
    silent = Company(figi="FIGI0002", ticker="EMPTY", name="Без отчётов", currency="RUB")
    db.add(silent)
    db.commit()
    moex.rows = [(earliest, 100.0)]

    result = backfill_all_companies(db)

    assert result == {"TEST": 1}


def test_one_broken_company_does_not_stop_the_rest(db, company, moex):
    """MOEX упал по одному тикеру — остальные всё равно обновляются."""
    earliest = TODAY - timedelta(days=5)
    _report(db, company, earliest)
    broken = Company(figi="FIGI0003", ticker="BROKEN", name="Сломанная", currency="RUB")
    db.add(broken)
    db.commit()
    _report(db, broken, earliest)
    moex.raises_for = {"BROKEN"}
    moex.rows = [(earliest, 100.0)]

    result = backfill_all_companies(db)

    assert result == {"TEST": 1}
    assert "BROKEN" not in result
