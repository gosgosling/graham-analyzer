"""Тип компании определяет набор метрик — и не выводится из сектора.

Регрессия, ради которой написан файл: набор полей отчёта брался из
`Company.sector`, а T-Invest кладёт в `financial` и Сбербанк, и АФК Систему,
и страховщика, и биржу. В результате холдинг получал банковский отчёт,
норматив достаточности капитала и стоимость риска — показатели, которых у
него не существует.
"""
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Company, FinancialReport
from app.models.enums import (
    CompanyType,
    PeriodType,
    ReportSource,
    company_type_to_report_type,
)
from app.services.analysis.sector_profiles import resolve_profile
from app.services.companies.company_service import set_company_type


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def _company(db, ticker: str, sector: str, company_type: str) -> Company:
    company = Company(
        figi=f"FIGI{ticker}", ticker=ticker, name=ticker, currency="RUB",
        sector=sector, company_type=company_type,
    )
    db.add(company)
    db.commit()
    return company


def _report(db, company: Company, report_type: str) -> FinancialReport:
    report = FinancialReport(
        company_id=company.id, period_type=PeriodType.ANNUAL, fiscal_year=2024,
        accounting_standard="IFRS", consolidated=True, report_date=date(2024, 12, 31),
        source=ReportSource.MANUAL, report_type=report_type, currency="RUB",
    )
    db.add(report)
    db.commit()
    return report


# ─── Соответствие типа и набора полей ────────────────────────────────────────


def test_only_lender_gets_bank_report_fields():
    assert company_type_to_report_type(CompanyType.LENDER.value) == "bank"

    for other in (CompanyType.INDUSTRIAL, CompanyType.INSURANCE,
                  CompanyType.HOLDING, CompanyType.HYBRID):
        assert company_type_to_report_type(other.value) == "general"


def test_hybrid_is_not_a_bank():
    """У Яндекса и МОЕХ внутри финбизнес, но отчётность — не банковская.

    Финансовый сегмент оценивается отдельно; подменять им отчётность всей
    компании нельзя, иначе выручка ИТ-бизнеса встанет в строку процентных
    доходов.
    """
    assert company_type_to_report_type("hybrid") == "general"


def test_unknown_type_falls_back_to_general():
    assert company_type_to_report_type(None) == "general"
    assert company_type_to_report_type("что-то новое") == "general"


# ─── Профиль порогов ─────────────────────────────────────────────────────────


def test_financial_sector_holding_does_not_get_bank_thresholds():
    """АФК Система: сектор financial, тип holding — пороги не банковские."""
    profile = resolve_profile("financial", report_type="general")

    assert profile.key != "bank"
    # Норматив достаточности капитала у холдинга не считается
    assert "cir" not in profile.bands


def test_lender_gets_bank_thresholds():
    assert resolve_profile("financial", report_type="bank").key == "bank"


# ─── Смена типа аналитиком ───────────────────────────────────────────────────


def test_switching_type_rewrites_report_kind(db):
    """Тип поменяли — набор полей у сохранённых отчётов идёт следом.

    Иначе у бывшего «банка» остаются банковские отчёты: интерфейс покажет
    стоимость риска по компании, у которой нет кредитного портфеля.
    """
    company = _company(db, "AFKS", "financial", CompanyType.LENDER.value)
    _report(db, company, "bank")

    set_company_type(db, company.id, "holding")

    assert company.company_type == "holding"
    assert db.query(FinancialReport).first().report_type == "general"


def test_switching_to_lender_marks_reports_as_bank(db):
    company = _company(db, "SVCB", "financial", CompanyType.INDUSTRIAL.value)
    _report(db, company, "general")

    set_company_type(db, company.id, "lender")

    assert db.query(FinancialReport).first().report_type == "bank"


def test_typo_in_type_is_rejected(db):
    """Опечатка не должна молча превратить компанию в промышленную."""
    company = _company(db, "SBER", "financial", CompanyType.LENDER.value)

    with pytest.raises(ValueError, match="Неизвестный тип"):
        set_company_type(db, company.id, "lendr")

    assert company.company_type == "lender"
