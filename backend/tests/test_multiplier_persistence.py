"""Сохранение мультипликаторов в кэш: что именно попадает в строку Multiplier.

Расчёт покрыт в `test_calc_multipliers.py`, а здесь — слой записи: он берёт
словарь из `calculate_multipliers` и раскладывает по колонкам. Раньше это были
два списка присвоений по двадцать строк, скопированных друг у друга, и списки
уже разошлись. Тесты фиксируют, какие поля должны оказаться в записи, чтобы
замена копипасты на список полей ничего не потеряла — и чтобы следующее поле
Грэма нельзя было забыть в одной из копий.

База — SQLite в памяти: схема моделей переносима, Postgres не нужен.
"""
from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Company, FinancialReport, Multiplier  # noqa: F401
from app.models.enums import AccountingStandard, PeriodType, ReportSource
from app.services.analysis.multiplier_service import (
    save_current_multiplier,
    save_report_based_multiplier,
)


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


def _report(db, company: Company, **overrides) -> FinancialReport:
    """Годовой отчёт промышленной компании: круглые числа, считается в уме."""
    fields = {
        "company_id": company.id,
        "period_type": PeriodType.ANNUAL,
        "fiscal_year": 2025,
        "accounting_standard": AccountingStandard.IFRS,
        "consolidated": True,
        "report_date": date(2025, 12, 31),
        "source": ReportSource.MANUAL,
        "report_type": "general",
        "currency": "RUB",
        "price_per_share": 100.0,
        "shares_outstanding": 1_000_000_000,
        "revenue": 50_000.0,
        "net_income": 10_000.0,
        "equity": 50_000.0,
        "total_assets": 100_000.0,
        "total_liabilities": 25_000.0,
        "current_assets": 30_000.0,
        "current_liabilities": 15_000.0,
        "operating_cash_flow": 15_000.0,
        "capex": 5_000.0,
        "dividends_paid": True,
        "dividends_per_share": 6.0,
    }
    fields.update(overrides)
    report = FinancialReport(**fields)
    db.add(report)
    db.commit()
    return report


# ─── type="current": снимок «на сегодня» из LTM-агрегации ────────────────────


def _current_payload(**overrides) -> dict:
    payload = {
        "price_used": 100.0,
        "shares_used": 1_000_000_000,
        "market_cap": 100_000.0,
        "ltm_net_income": 10_000.0,
        "ltm_revenue": 50_000.0,
        "ltm_dividends_per_share": 6.0,
        "ltm_special_dividends_per_share": 1.0,
        "pe_ratio": 10.0,
        "pb_ratio": 2.0,
        "roe": 20.0,
        "debt_to_equity": 0.5,
        "current_ratio": 2.0,
        "dividend_yield": 6.0,
        "dividend_yield_regular": 5.0,
        "cost_to_income": None,
        "ltm_fcf": 10_000.0,
        "ltm_operating_cash_flow": 15_000.0,
        "ltm_capex": 5_000.0,
        "price_to_fcf": 10.0,
        "fcf_to_net_income": 1.0,
        "net_debt": 15_000.0,
        "net_debt_to_fcf": 1.5,
    }
    payload.update(overrides)
    return payload


def test_current_snapshot_stores_every_metric(db, company):
    """Все посчитанные метрики доходят до строки кэша, ни одна не теряется."""
    payload = _current_payload()

    row = save_current_multiplier(db, company.id, payload)

    assert row.type == "current"
    assert row.date == date.today()
    for field, expected in payload.items():
        if expected is None:
            assert getattr(row, field) is None, field
        else:
            assert float(getattr(row, field)) == expected, field


def test_current_snapshot_is_idempotent_within_a_day(db, company):
    """Повторный расчёт за тот же день обновляет запись, а не плодит вторую."""
    save_current_multiplier(db, company.id, _current_payload())
    row = save_current_multiplier(db, company.id, _current_payload(pe_ratio=12.5))

    assert float(row.pe_ratio) == 12.5
    assert db.query(Multiplier).filter(Multiplier.type == "current").count() == 1


def test_current_snapshot_takes_balance_from_the_referenced_report(db, company):
    """Балансовые поля берутся из отчёта, на который ссылается снимок."""
    report = _report(db, company)

    row = save_current_multiplier(
        db, company.id, _current_payload(balance_report_id=report.id)
    )

    assert row.report_id == report.id
    assert float(row.equity) == 50_000.0
    assert float(row.total_liabilities) == 25_000.0
    assert float(row.current_assets) == 30_000.0


def test_current_snapshot_converts_balance_to_rubles(db, company):
    """Отчёт в долларах: в кэше баланс уже в рублях (курс из отчёта)."""
    report = _report(db, company, currency="USD", exchange_rate=90.0, equity=1_000.0)

    row = save_current_multiplier(
        db, company.id, _current_payload(balance_report_id=report.id)
    )

    assert float(row.equity) == 90_000.0


def test_current_snapshot_without_balance_report_leaves_balance_empty(db, company):
    row = save_current_multiplier(db, company.id, _current_payload())

    assert row.report_id is None
    assert row.equity is None


# ─── type="report_based": запись на дату отчёта ──────────────────────────────


def test_report_based_row_holds_metrics_flow_and_balance(db, company):
    """Метрики — из расчёта, поток и баланс — из самого отчёта, в рублях."""
    report = _report(db, company)

    row = save_report_based_multiplier(db, report)

    assert row is not None
    assert row.type == "report_based"
    assert row.report_id == report.id
    assert row.date == report.report_date
    # 100 ₽ × 1 млрд шт = 100 000 млн ₽ капитализации, прибыль 10 000 млн → P/E 10
    assert float(row.market_cap) == 100_000.0
    assert float(row.pe_ratio) == 10.0
    assert float(row.pb_ratio) == 2.0
    # Поток за период — из отчёта, а не из LTM-агрегации
    assert float(row.ltm_net_income) == 10_000.0
    assert float(row.ltm_revenue) == 50_000.0
    assert float(row.ltm_dividends_per_share) == 6.0
    # FCF = OCF − CAPEX = 15 000 − 5 000
    assert float(row.ltm_fcf) == 10_000.0
    assert float(row.ltm_operating_cash_flow) == 15_000.0
    assert float(row.ltm_capex) == 5_000.0
    assert float(row.equity) == 50_000.0
    assert float(row.current_liabilities) == 15_000.0


def test_report_based_flow_is_converted_to_rubles(db, company):
    """Отчёт в долларах: поток тоже пересчитан по курсу отчёта."""
    report = _report(
        db, company, currency="USD", exchange_rate=90.0,
        net_income=100.0, revenue=500.0, dividends_per_share=1.0,
        operating_cash_flow=200.0, capex=50.0,
    )

    row = save_report_based_multiplier(db, report)

    assert row is not None
    assert float(row.ltm_net_income) == 9_000.0
    assert float(row.ltm_revenue) == 45_000.0
    assert float(row.ltm_dividends_per_share) == 90.0
    assert float(row.ltm_fcf) == 13_500.0  # (200 − 50) × 90


def test_report_based_is_idempotent_and_follows_moved_report_date(db, company):
    """Один отчёт — одна запись; при сдвиге report_date старая не остаётся."""
    report = _report(db, company)
    save_report_based_multiplier(db, report)

    report.report_date = date(2025, 12, 30)
    db.commit()
    row = save_report_based_multiplier(db, report)

    assert row is not None
    assert row.date == date(2025, 12, 30)
    assert db.query(Multiplier).filter(Multiplier.type == "report_based").count() == 1


def test_interim_report_gets_no_report_based_row(db, company):
    """Промежуточные отчёты в историю не попадают — там нет полного года."""
    report = _report(
        db, company, period_type=PeriodType.SEMI_ANNUAL, report_date=date(2025, 6, 30)
    )

    assert save_report_based_multiplier(db, report) is None
    assert db.query(Multiplier).count() == 0


def test_report_without_price_still_gets_row(db, company):
    """До выхода на биржу цены нет, но год обязан быть в истории.

    Подставлять вместо неё цену размещения нельзя: получился бы P/E, где
    числитель из года IPO, а знаменатель из года, когда бумага не торговалась.
    Поэтому цена и всё, что от неё зависит, остаются пустыми, а выручка,
    капитал, ROE и поток считаются как обычно — по ним и видно динамику.
    """
    report = _report(db, company, price_per_share=None, shares_outstanding=None)

    saved = save_report_based_multiplier(db, report)

    assert saved is not None
    assert saved.price_used is None
    assert saved.market_cap is None
    assert saved.pe_ratio is None
    assert saved.pb_ratio is None
    # Не зависят от цены — обязаны посчитаться
    assert float(saved.roe) == 20.0
    assert float(saved.debt_to_equity) == 0.5
    assert float(saved.current_ratio) == 2.0
    assert float(saved.ltm_revenue) == 50_000.0


def test_empty_draft_report_is_skipped(db, company):
    """Пустой черновик в историю не попадает: строка несла бы только год."""
    report = _report(
        db, company,
        price_per_share=None, shares_outstanding=None,
        revenue=None, net_income=None, equity=None, total_assets=None,
    )

    assert save_report_based_multiplier(db, report) is None
    assert db.query(Multiplier).count() == 0
