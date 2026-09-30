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
            self.boards: List[str] = []
            self.rows: List[Tuple[date, float]] = []
            self.raises_for: set[str] = set()

        def __call__(self, ticker: str, from_date: date, till_date: date,
                     board: str = "TQBR"):
            self.calls.append((ticker, from_date, till_date))
            self.boards.append(board)
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
    """Ряд покрывает всё — от первого отчёта до вчера: в MOEX не ходим."""
    start = TODAY - timedelta(days=30)
    _report(db, company, start)
    db.add(StockPrice(company_id=company.id, date=start, price=99.0, source="moex"))
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
    start = TODAY - timedelta(days=30)
    _report(db, company, start)
    last_stored = TODAY - timedelta(days=10)
    db.add(StockPrice(company_id=company.id, date=start, price=89.0, source="moex"))
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


# ─── Докачка истории назад ───────────────────────────────────────────────────


def test_history_is_filled_backwards_when_series_starts_late(db, company, moex):
    """Ряд начат с середины — недостающее начало докачивается назад.

    Ради этого случая правило и появилось: докачка шла только вперёд, и ряд,
    начатый однажды 21 марта 2026 года, так и оставался полугодовым у всех
    компаний — назад его не дотягивало ничто.
    """
    start = TODAY - timedelta(days=200)
    _report(db, company, start)
    first_stored = TODAY - timedelta(days=40)
    db.add(StockPrice(company_id=company.id, date=first_stored, price=90.0, source="moex"))
    db.add(StockPrice(company_id=company.id, date=YESTERDAY, price=95.0, source="moex"))
    db.commit()
    moex.rows = [(start, 70.0)]

    added = backfill_company_prices(db, company)

    assert added == 1
    assert moex.calls == [("TEST", start, first_stored - timedelta(days=1))]


def test_backwards_and_forwards_in_one_pass(db, company, moex):
    """Недостаёт и начала, и последних дней — оба диапазона за один вызов."""
    start = TODAY - timedelta(days=200)
    _report(db, company, start)
    first_stored = TODAY - timedelta(days=40)
    last_stored = TODAY - timedelta(days=10)
    db.add(StockPrice(company_id=company.id, date=first_stored, price=90.0, source="moex"))
    db.add(StockPrice(company_id=company.id, date=last_stored, price=91.0, source="moex"))
    db.commit()

    backfill_company_prices(db, company)

    assert moex.calls == [
        ("TEST", start, first_stored - timedelta(days=1)),
        ("TEST", last_stored + timedelta(days=1), YESTERDAY),
    ]


def test_small_gap_at_the_start_is_not_a_hole(db, company, moex):
    """Первый торговый день после отчёта — не сама дата отчёта.

    Выходные, праздники, январские каникулы биржи: ряд, начавшийся через
    неделю после отчёта, полный, и перезапрашивать его начало незачем.
    """
    start = TODAY - timedelta(days=60)
    _report(db, company, start)
    db.add(StockPrice(company_id=company.id, date=start + timedelta(days=7),
                      price=90.0, source="moex"))
    db.add(StockPrice(company_id=company.id, date=YESTERDAY, price=95.0, source="moex"))
    db.commit()

    assert backfill_company_prices(db, company) == 0
    assert moex.calls == []


def test_history_is_not_requested_before_the_floor(db, company, moex):
    """Отчёты с 2008 года — но цены раньше 2010-го не грузятся."""
    _report(db, company, date(2008, 12, 31))

    backfill_company_prices(db, company)

    assert moex.calls[0][1] == price_history_service.HISTORY_FLOOR


def test_legacy_boards_fill_years_before_unification(db, company, moex):
    """До 9 июня 2014 года бумага могла торговаться не в TQBR.

    У Башнефти 2012–2013 годы лежат в режиме EQNE, а в TQBR свечи начинаются
    только с 9 июня 2014-го. Запрос по одному основному режиму возвращал ряд,
    обрезанный ровно по этой дате.
    """
    _report(db, company, date(2012, 1, 1))
    tqbr = [(date(2014, 6, 9), 2464.7)]
    legacy = [(date(2012, 1, 3), 1380.0), (date(2014, 6, 9), 9999.0)]

    def fake(ticker, from_date, till_date, board="TQBR"):
        moex.calls.append((ticker, from_date, till_date))
        moex.boards.append(board)
        return list(tqbr if board == "TQBR" else legacy if board == "EQNE" else [])

    price_history_service.get_price_history = fake

    backfill_company_prices(db, company)

    stored = _stored(db, company.id)
    assert (date(2012, 1, 3), 1380.0) in stored
    # День, найденный в основном режиме, запасным не перекрывается.
    assert (date(2014, 6, 9), 2464.7) in stored
    assert set(moex.boards) >= {"TQBR", "TQNE", "EQBR", "EQNE"}


def test_legacy_boards_are_not_asked_after_unification(db, company, moex):
    """Для лет после объединения режимов запасные не запрашиваются вовсе."""
    _report(db, company, TODAY - timedelta(days=30))

    backfill_company_prices(db, company)

    assert moex.boards == ["TQBR"]


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


# ─── Бумага сменила имя ──────────────────────────────────────────────────────

def test_history_before_a_rename_is_asked_under_the_old_name(db, company, moex):
    """ISS хранит торги под тем символом, что был в тот день, и связи между
    старым и новым именем у биржи нет. Запрос всей истории по нынешнему тикеру
    возвращал пустоту за годы до переименования — цена лежала под FIVE."""
    company.ticker = "X5"
    company.former_tickers = [{"ticker": "FIVE", "until": "2024-11-22"}]
    db.commit()
    _report(db, company, date(2021, 12, 31))

    backfill_company_prices(db, company)

    assert moex.calls == [
        ("FIVE", date(2021, 12, 31), date(2024, 11, 22)),
        ("X5", date(2024, 11, 23), YESTERDAY),
    ]


def _main_board(moex) -> List[Tuple[str, date, date]]:
    """Запросы по основному режиму: запасные доски — отдельная забота."""
    return [call for call, board in zip(moex.calls, moex.boards) if board == "TQBR"]


def test_a_chain_of_three_names_is_split_by_each_rename(db, company, moex):
    """ОГК-4 → Э.ОН Россия → Юнипро: у одной компании три символа.

    Самое старое звено сюда не попадает: OGKD кончился в 2007 году, а история
    не грузится раньше HISTORY_FLOOR. Спрашивать его не за что."""
    company.ticker = "UPRO"
    company.former_tickers = [
        {"ticker": "EONR", "until": "2016-06-30"},
        {"ticker": "OGKD", "until": "2007-04-24"},
    ]
    db.commit()
    _report(db, company, date(2006, 12, 31))

    backfill_company_prices(db, company)

    assert _main_board(moex) == [
        ("EONR", date(2010, 1, 1), date(2016, 6, 30)),
        ("UPRO", date(2016, 7, 1), YESTERDAY),
    ]


def test_every_link_of_the_chain_is_asked_when_all_are_in_range(db, company, moex):
    company.ticker = "UPRO"
    company.former_tickers = [
        {"ticker": "EONR", "until": "2016-06-30"},
        {"ticker": "OGKD", "until": "2007-04-24"},
    ]
    db.commit()
    _report(db, company, date(2006, 12, 31))

    backfill_company_prices(db, company, force_from=date(2005, 1, 1))

    assert _main_board(moex) == [
        ("OGKD", date(2005, 1, 1), date(2007, 4, 24)),
        ("EONR", date(2007, 4, 25), date(2016, 6, 30)),
        ("UPRO", date(2016, 7, 1), YESTERDAY),
    ]


def test_a_name_retired_before_the_range_is_not_asked(db, company, moex):
    """Отчёты начинаются после переименования — старый символ не нужен."""
    company.ticker = "VKCO"
    company.former_tickers = [{"ticker": "MAIL", "until": "2021-12-13"}]
    db.commit()
    _report(db, company, date(2022, 12, 31))

    backfill_company_prices(db, company)

    assert moex.calls == [("VKCO", date(2022, 12, 31), YESTERDAY)]


def test_a_company_that_never_changed_its_name_asks_once(db, company, moex):
    _report(db, company, date(2024, 12, 31))

    backfill_company_prices(db, company)

    assert moex.calls == [("TEST", date(2024, 12, 31), YESTERDAY)]


def test_the_boundary_day_belongs_to_the_old_name(db, company, moex):
    """`until` — последний день старого символа, а не первый день нового."""
    company.ticker = "CNRU"
    company.former_tickers = [{"ticker": "CIAN", "until": "2025-04-02"}]
    db.commit()
    _report(db, company, date(2025, 4, 2))

    backfill_company_prices(db, company)

    assert moex.calls[0] == ("CIAN", date(2025, 4, 2), date(2025, 4, 2))
    assert moex.calls[1] == ("CNRU", date(2025, 4, 3), YESTERDAY)
