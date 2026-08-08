"""Выбор ветки LTM в `get_ltm_data` — какой источник взят и что попало в поток.

`test_ltm.py` проверяет арифметику на чистых хелперах. Но до арифметики
`get_ltm_data` выбирает источник: годовой отчёт, формула по промежуточному,
сумма четырёх кварталов или частичная сумма «сколько нашлось». Ошибка выбора
не падает — она молча занижает или завышает прибыль, а вместе с ней P/E,
дивидендную доходность и вердикт по Грэму.

Ветки ходят в базу, поэтому здесь поднимается SQLite в памяти: схема моделей
переносима (`native_enum=False`, никаких JSONB), тест остаётся быстрым и
Postgres не требует.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Company, FinancialReport  # noqa: F401 — регистрирует все таблицы
from app.models.enums import AccountingStandard, PeriodType, ReportSource
from app.services.analysis.multiplier_service import get_ltm_data


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


def _add_report(
    db,
    company: Company,
    *,
    year: int,
    period: PeriodType = PeriodType.ANNUAL,
    quarter: Optional[int] = None,
    month_end: int = 12,
    net_income: Optional[float] = None,
    revenue: Optional[float] = None,
    dividends_per_share: Optional[float] = None,
    equity: Optional[float] = None,
    report_type: str = "general",
    net_interest_income: Optional[float] = None,
    accounting_standard: str = AccountingStandard.IFRS,
    consolidated: bool = True,
) -> FinancialReport:
    day = 31 if month_end in (12, 3) else 30
    report = FinancialReport(
        company_id=company.id,
        period_type=period,
        fiscal_year=year,
        fiscal_quarter=quarter,
        accounting_standard=accounting_standard,
        consolidated=consolidated,
        report_date=date(year, month_end, day),
        source=ReportSource.MANUAL,
        report_type=report_type,
        currency="RUB",
        net_income=net_income,
        revenue=revenue,
        dividends_paid=dividends_per_share is not None,
        dividends_per_share=dividends_per_share,
        equity=equity,
        net_interest_income=net_interest_income,
    )
    db.add(report)
    db.commit()
    return report


# ─── Годовой отчёт ───────────────────────────────────────────────────────────


def test_latest_annual_is_taken_as_is(db, company):
    """Свежий годовой отчёт — сам себе LTM, без сложений."""
    _add_report(db, company, year=2024, net_income=1_000.0, revenue=5_000.0)
    _add_report(db, company, year=2025, net_income=1_200.0, revenue=6_000.0)

    ltm = get_ltm_data(db, company.id)

    assert ltm["source"] == "annual"
    assert ltm["ltm_net_income"] == 1_200.0
    assert ltm["ltm_revenue"] == 6_000.0
    assert ltm["balance_report"].fiscal_year == 2025


def test_balance_report_is_always_the_freshest_report(db, company):
    """Баланс берётся из самого свежего отчёта, даже если поток посчитан иначе."""
    _add_report(db, company, year=2024, net_income=1_000.0, equity=50_000.0)
    _add_report(
        db, company, year=2025, period=PeriodType.SEMI_ANNUAL, month_end=6,
        net_income=700.0, equity=53_000.0,
    )

    ltm = get_ltm_data(db, company.id)

    assert ltm["balance_report"].period_type == PeriodType.SEMI_ANNUAL
    assert float(ltm["balance_report"].equity) == 53_000.0


# ─── Промежуточный отчёт: формула FY + YTD − prior YTD ───────────────────────


def test_semi_annual_uses_interim_formula(db, company):
    """H1 2026 + FY2025 − H1 2025 = скользящий год, а не сумма полугодий."""
    _add_report(db, company, year=2025, period=PeriodType.SEMI_ANNUAL, month_end=6, net_income=400.0)
    _add_report(db, company, year=2025, net_income=1_000.0)
    _add_report(db, company, year=2026, period=PeriodType.SEMI_ANNUAL, month_end=6, net_income=500.0)

    ltm = get_ltm_data(db, company.id)

    assert ltm["source"] == "semi_annual_derived"
    assert ltm["ltm_net_income"] == 1_100.0  # 500 + 1000 − 400


def test_nine_months_report_uses_interim_formula(db, company):
    """9 месяцев МСФО (ЛУКОЙЛ и подобные) — Q3 с накопительным итогом.

    LTM = 9М_2026 + FY2025 − 9М_2025, то есть октябрь 2025 – сентябрь 2026.
    """
    _add_report(db, company, year=2025, period=PeriodType.QUARTERLY, quarter=3, month_end=9, net_income=300.0)
    _add_report(db, company, year=2025, net_income=1_000.0)
    _add_report(db, company, year=2026, period=PeriodType.QUARTERLY, quarter=3, month_end=9, net_income=450.0)

    ltm = get_ltm_data(db, company.id)

    assert ltm["source"] == "quarterly_3_derived"
    assert ltm["ltm_net_income"] == 1_150.0  # 450 + 1000 − 300


def test_interim_formula_ignores_reports_of_another_standard(db, company):
    """РСБУ-годовой не подставляется в формулу к МСФО-полугодию: базы разные."""
    _add_report(db, company, year=2025, period=PeriodType.SEMI_ANNUAL, month_end=6, net_income=400.0)
    _add_report(db, company, year=2025, net_income=1_000.0, accounting_standard=AccountingStandard.RAS)
    _add_report(db, company, year=2026, period=PeriodType.SEMI_ANNUAL, month_end=6, net_income=500.0)

    ltm = get_ltm_data(db, company.id)

    assert ltm["source"] != "semi_annual_derived"
    assert ltm["ltm_net_income"] != 1_100.0


# ─── Кварталы ────────────────────────────────────────────────────────────────


def test_nine_months_without_last_year_pair_falls_back_to_annual(db, company):
    """Первый введённый 9М-отчёт: пары за прошлый год нет — берём годовой.

    Свежий YTD в LTM не превращается, но и не подменяет год: 9 месяцев,
    выданные за 12, занизили бы прибыль на четверть.
    """
    _add_report(db, company, year=2025, net_income=1_000.0)
    _add_report(db, company, year=2026, period=PeriodType.QUARTERLY, quarter=3, month_end=9, net_income=800.0)

    ltm = get_ltm_data(db, company.id)

    assert ltm["source"] == "annual"
    assert ltm["ltm_net_income"] == 1_000.0


def test_ytd_for_four_quarters_is_taken_as_full_year(db, company):
    """YTD за 4 квартала — это уже год: берём отчёт целиком, ничего не складывая."""
    for quarter, month, profit in ((1, 3, 100.0), (3, 9, 400.0), (4, 12, 600.0)):
        _add_report(
            db, company, year=2026, period=PeriodType.QUARTERLY,
            quarter=quarter, month_end=month, net_income=profit,
        )

    ltm = get_ltm_data(db, company.id)

    assert ltm["source"] == "ytd_full_year"
    assert ltm["ltm_net_income"] == 600.0


def test_annual_wins_over_partial_quarter_sum(db, company):
    """Двух кварталов мало — берём годовой целиком, а не половину года.

    Это защита от тихого занижения: сумма двух кварталов выглядит как прибыль
    за год и роняет P/E вдвое.
    """
    _add_report(db, company, year=2025, net_income=1_000.0)
    _add_report(db, company, year=2026, period=PeriodType.QUARTERLY, quarter=1, month_end=3, net_income=100.0)
    _add_report(db, company, year=2026, period=PeriodType.QUARTERLY, quarter=2, month_end=6, net_income=150.0)

    ltm = get_ltm_data(db, company.id)

    assert ltm["source"] == "annual"
    assert ltm["ltm_net_income"] == 1_000.0


def test_ytd_reports_are_never_summed_with_each_other(db, company):
    """Только 3М и 9М без годового — LTM не считается, а не складывается.

    3М + 9М даёт формально 12 месяцев, но первый квартал в этой сумме учтён
    дважды, а четвёртый не учтён вовсе. Пустой мультипликатор честнее.
    """
    _add_report(db, company, year=2026, period=PeriodType.QUARTERLY, quarter=1, month_end=3, net_income=100.0)
    _add_report(db, company, year=2026, period=PeriodType.QUARTERLY, quarter=3, month_end=9, net_income=400.0)

    ltm = get_ltm_data(db, company.id)

    assert ltm["source"] == "insufficient"
    assert ltm["ltm_net_income"] is None
    assert ltm["balance_report"].fiscal_quarter == 3  # баланс всё равно свежий


# ─── Дивиденды, банки, пустая база ───────────────────────────────────────────


def test_dividends_not_paid_do_not_leak_into_ltm(db, company):
    """Дивиденд из отчёта, где выплат не было, в LTM не попадает."""
    _add_report(db, company, year=2025, net_income=1_000.0, dividends_per_share=None)

    ltm = get_ltm_data(db, company.id)

    assert ltm["ltm_dividends_per_share"] is None


def test_bank_fields_are_aggregated_for_bank_reports(db, company):
    """Для банка к потоку добавляются процентные и комиссионные доходы."""
    _add_report(
        db, company, year=2025, net_income=1_000.0,
        report_type="bank", net_interest_income=800.0,
    )

    ltm = get_ltm_data(db, company.id)

    assert ltm["ltm_net_interest_income"] == 800.0


def test_hybrid_report_aggregates_bank_fields_too(db, company):
    """Гибриду финсегмент нужен, хотя тип отчёта у него общий.

    У Яндекса банк живёт внутри обычной отчётности: `report_type` остаётся
    general, но портфель и резервы заполнены. Раньше агрегация смотрела на
    тип отчёта и такие поля отбрасывала.
    """
    _add_report(db, company, year=2025, net_income=1_000.0, net_interest_income=800.0)

    ltm = get_ltm_data(db, company.id)

    assert ltm["ltm_net_interest_income"] == 800.0


def test_industrial_report_has_no_bank_flows(db, company):
    """У промышленной компании банковских полей нет — и в LTM их не появится."""
    _add_report(db, company, year=2025, net_income=1_000.0)

    ltm = get_ltm_data(db, company.id)

    assert ltm["ltm_net_interest_income"] is None
    assert ltm["ltm_provisions"] is None


def test_company_without_reports_returns_none(db, company):
    assert get_ltm_data(db, company.id) is None
