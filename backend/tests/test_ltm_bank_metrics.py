"""Банковские показатели по скользящему году.

Показатели вида «поток ÷ баланс» — ROA, маржа, стоимость риска и
фондирования — ломаются на промежуточной отчётности: в числителе полгода, в
знаменателе полный баланс. Домножение периода до года это лечит, но ценой
допущения, что оставшиеся месяцы будут как прошедшие. Когда есть три отчёта,
допущение не нужно — и проверяется здесь именно предпочтение факта экстраполяции.

Цифры взяты из отчётности Сбера за 2025 и первое полугодие 2026, чтобы
расхождение между двумя способами было видно на настоящих данных.
"""
from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Company, FinancialReport  # noqa: F401 — регистрирует таблицы
from app.models.enums import AccountingStandard, PeriodType, ReportSource
from app.models.key_rate import KeyRate
from app.services.analysis.multiplier_service import compute_ltm_bank_metrics


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
def bank(db) -> Company:
    company = Company(figi="FIGI_BANK", ticker="BANK", name="Банк", currency="RUB")
    db.add(company)
    db.add(KeyRate(year=2026, avg_rate=14.98))
    db.commit()
    return company


def _report(db, company, *, year, period, month_end, report_type="bank", **fields):
    report = FinancialReport(
        company_id=company.id,
        period_type=period,
        fiscal_year=year,
        accounting_standard=AccountingStandard.IFRS,
        consolidated=True,
        report_date=date(year, month_end, 31 if month_end == 12 else 30),
        source=ReportSource.MANUAL,
        report_type=report_type,
        currency="RUB",
        **fields,
    )
    db.add(report)
    db.commit()
    return report


# Баланс на 30.06.2026 и потоки Сбера, млн ₽
_BALANCE = dict(
    total_assets=69_141_500.0,
    gross_loans=48_473_100.0,
    loan_loss_allowance=2_605_100.0,
    npl_loans=2_627_800.0,
    customer_deposits=49_132_800.0,
)


def _sber_three_reports(db, bank):
    _report(db, bank, year=2025, period=PeriodType.ANNUAL, month_end=12,
            net_income=1_707_400.0, net_interest_income=3_556_000.0,
            provisions=646_600.0, interest_expense=5_933_800.0)
    _report(db, bank, year=2025, period=PeriodType.SEMI_ANNUAL, month_end=6,
            net_income=859_000.0, net_interest_income=1_674_200.0,
            provisions=364_800.0, interest_expense=3_150_200.0)
    return _report(db, bank, year=2026, period=PeriodType.SEMI_ANNUAL, month_end=6,
                   net_income=1_019_100.0, net_interest_income=2_051_100.0,
                   provisions=332_700.0, interest_expense=2_747_600.0, **_BALANCE)


def test_flows_come_from_rolling_twelve_months(db, bank):
    """ROA считается от прибыли за 12 месяцев, а не от удвоенного полугодия."""
    _sber_three_reports(db, bank)

    metrics = compute_ltm_bank_metrics(db, bank.id)

    assert metrics["flow_basis"] == "ltm"
    # 1 707,4 + 1 019,1 − 859,0 = 1 867,5 млрд ÷ 69 141,5 = 2,70%
    assert metrics["roa"] == pytest.approx(2.70, abs=0.01)
    assert metrics["net_interest_margin"] == pytest.approx(5.69, abs=0.01)
    assert metrics["cost_of_risk"] == pytest.approx(1.27, abs=0.01)


def test_annualisation_would_have_given_a_different_answer(db, bank):
    """Страховка от «а вдруг разницы нет»: удвоение полугодия завышает ROA."""
    _sber_three_reports(db, bank)

    ltm = compute_ltm_bank_metrics(db, bank.id)["roa"]
    annualised = 1_019_100.0 * 2 / 69_141_500.0 * 100

    assert annualised == pytest.approx(2.95, abs=0.01)
    assert ltm < annualised


def test_balance_ratios_are_taken_from_the_latest_report(db, bank):
    """Знаменатели — на отчётную дату, LTM их не касается."""
    _sber_three_reports(db, bank)

    metrics = compute_ltm_bank_metrics(db, bank.id)

    assert metrics["npl_ratio"] == pytest.approx(5.42, abs=0.01)
    assert metrics["npl_coverage"] == pytest.approx(99.14, abs=0.01)


def test_without_prior_year_interim_uses_last_full_year(db, bank):
    """Пары для формулы нет — берём последний полный год, как это делает P/E.

    Числа настоящие, но период закончился раньше отчётной даты, поэтому
    показатель помечен отдельно: прибыль 2025 года на балансе середины 2026
    занижает отдачу, и выдавать это за скользящий год нельзя.
    """
    _report(db, bank, year=2025, period=PeriodType.ANNUAL, month_end=12,
            net_income=1_707_400.0, provisions=646_600.0)
    _report(db, bank, year=2026, period=PeriodType.SEMI_ANNUAL, month_end=6,
            net_income=1_019_100.0, provisions=332_700.0, **_BALANCE)

    metrics = compute_ltm_bank_metrics(db, bank.id)

    assert metrics["flow_basis"] == "prior_full_year"
    assert metrics["roa"] == pytest.approx(1_707_400 / 69_141_500 * 100, abs=0.01)


def test_annual_report_needs_no_conversion(db, bank):
    """Свежий отчёт годовой — LTM совпадает с ним, пометка это признаёт."""
    _report(db, bank, year=2025, period=PeriodType.ANNUAL, month_end=12,
            net_income=1_707_400.0, provisions=646_600.0, **_BALANCE)

    metrics = compute_ltm_bank_metrics(db, bank.id)

    assert metrics["flow_basis"] == "reported"
    assert metrics["roa"] == pytest.approx(1_707_400 / 69_141_500 * 100, abs=0.01)


def test_not_a_bank_gets_nothing(db, bank):
    """У промышленной компании нет ни портфеля, ни Н1 — пустой блок лишний."""
    _report(db, bank, year=2025, period=PeriodType.ANNUAL, month_end=12,
            report_type="general", net_income=1_000.0, total_assets=10_000.0)

    assert compute_ltm_bank_metrics(db, bank.id) is None


def test_company_without_reports(db, bank):
    assert compute_ltm_bank_metrics(db, bank.id) is None
