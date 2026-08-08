"""Оценка холдинга по NAV.

Цифры — из базы на 31 июля 2026: МТС 365,7 млрд, Озон 615,5 млрд,
Сегежа 51,5 млрд. Доли владения условные, они вводятся аналитиком.

Главное, что проверяется: расчёт не врёт при незаполненных карточках.
На этапе набора базы у половины дочек нет ни цены, ни отчётов, и доля без
данных должна попадать в «неоценённые», а не тихо считаться нулём —
иначе NAV окажется занижен, а дисконт нарисуется красивым.
"""
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Company, FinancialReport, HoldingStake
from app.models.enums import CompanyType, PeriodType, ReportSource
from app.services.holdings.nav_service import compute_holding_nav


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def _company(db, ticker, price=None, shares=None, company_type="industrial", corp_debt=None):
    company = Company(
        figi=f"FIGI{ticker}", ticker=ticker, name=ticker, currency="RUB",
        company_type=company_type, current_price=price,
        corporate_center_net_debt=corp_debt,
    )
    db.add(company)
    db.commit()
    if shares is not None:
        db.add(FinancialReport(
            company_id=company.id, period_type=PeriodType.ANNUAL, fiscal_year=2025,
            accounting_standard="IFRS", consolidated=True, report_date=date(2025, 12, 31),
            source=ReportSource.MANUAL, report_type="general", currency="RUB",
            shares_issued=shares,
        ))
        db.commit()
    return company


def _stake(db, holding, name, share_pct, subsidiary=None, manual=None):
    stake = HoldingStake(
        holding_company_id=holding.id,
        subsidiary_company_id=subsidiary.id if subsidiary else None,
        name=name, share_pct=share_pct, manual_valuation=manual,
    )
    db.add(stake)
    db.commit()
    return stake


def test_public_stake_is_valued_from_subsidiary_card(db):
    """Доля в публичной дочке считается по её же карточке — без ручного ввода."""
    holding = _company(db, "AFKS", price=8.805, shares=9_650_000_000, company_type=CompanyType.HOLDING.value)
    mts = _company(db, "MTSS", price=183.0, shares=1_998_381_575)
    _stake(db, holding, "МТС", 42.09, subsidiary=mts)

    nav = compute_holding_nav(db, holding.id)
    stake = nav.stakes[0]

    assert stake.source == "market"
    assert stake.company_value == pytest.approx(365_703.8, abs=1)   # 365,7 млрд ₽
    assert stake.stake_value == pytest.approx(153_924.7, abs=1)     # 42,09% от неё
    assert nav.market_cap == pytest.approx(84_968.3, abs=1)         # сам холдинг


def test_private_asset_uses_manual_valuation(db):
    """Непубличный актив (Медси, Степь) оценивается руками — иначе выпадет вовсе."""
    holding = _company(db, "AFKS", price=8.805, shares=9_650_000_000, company_type=CompanyType.HOLDING.value)
    _stake(db, holding, "Медси", 95.0, manual=120_000)

    stake = compute_holding_nav(db, holding.id).stakes[0]

    assert stake.source == "manual"
    assert stake.stake_value == pytest.approx(114_000)


def test_unfilled_card_is_listed_as_unvalued_not_zero(db):
    """Дочка без цены не обнуляет долю: иначе NAV занижен, а дисконт красивый."""
    holding = _company(db, "AFKS", price=8.805, shares=9_650_000_000, company_type=CompanyType.HOLDING.value)
    mts = _company(db, "MTSS", price=183.0, shares=1_998_381_575)
    empty = _company(db, "MBNK", price=898.5)          # цена есть, отчётов нет
    _stake(db, holding, "МТС", 42.09, subsidiary=mts)
    _stake(db, holding, "МТС Банк", 10.0, subsidiary=empty)

    nav = compute_holding_nav(db, holding.id)

    assert nav.total_stakes == 2
    assert nav.valued_stakes == 1
    unvalued = [s for s in nav.stakes if s.stake_value is None][0]
    assert unvalued.missing == "нет количества акций в отчётах"
    # В сумму попала только оценённая доля
    assert nav.stakes_value == pytest.approx(153_924.7, abs=1)


def test_nav_subtracts_corporate_center_debt(db):
    """Долг центра вычитается: доли принадлежат холдингу, долг тоже его."""
    holding = _company(
        db, "AFKS", price=8.805, shares=9_650_000_000,
        company_type=CompanyType.HOLDING.value, corp_debt=330_000,
    )
    ozon = _company(db, "OZON", price=2844.0, shares=216_413_733)
    _stake(db, holding, "Озон", 31.8, subsidiary=ozon)

    nav = compute_holding_nav(db, holding.id)

    assert nav.stakes_value == pytest.approx(195_722.8, abs=1)
    assert nav.nav == pytest.approx(-134_277.2, abs=1)
    # При отрицательном NAV дисконт не считается: сравнивать не с чем
    assert nav.discount_pct is None


def test_discount_shows_how_much_cheaper_holding_trades(db):
    """Капитализация 85 млрд при NAV 260 млрд — дисконт 67%."""
    holding = _company(
        db, "AFKS", price=8.805, shares=9_650_000_000,
        company_type=CompanyType.HOLDING.value, corp_debt=330_000,
    )
    _stake(db, holding, "Публичные доли", 100.0, manual=390_000)
    _stake(db, holding, "Непубличные активы", 100.0, manual=200_000)

    nav = compute_holding_nav(db, holding.id)

    assert nav.nav == pytest.approx(260_000)
    assert nav.discount_pct == pytest.approx(67.32, abs=0.1)


def test_holding_without_stakes_is_not_an_error(db):
    """Холдинг только что заведён — интерфейс должен позвать добавить доли."""
    holding = _company(db, "SFIN", price=488.4, company_type=CompanyType.HOLDING.value)

    nav = compute_holding_nav(db, holding.id)

    assert nav is not None
    assert nav.total_stakes == 0
    assert nav.nav is None
