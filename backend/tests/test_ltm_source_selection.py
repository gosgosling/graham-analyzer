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

    ltm = get_ltm_data(db, company.id, as_of=date(2030, 1, 1))

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

    ltm = get_ltm_data(db, company.id, as_of=date(2030, 1, 1))

    assert ltm["balance_report"].period_type == PeriodType.SEMI_ANNUAL
    assert float(ltm["balance_report"].equity) == 53_000.0


# ─── Промежуточный отчёт: формула FY + YTD − prior YTD ───────────────────────


def test_semi_annual_uses_interim_formula(db, company):
    """H1 2026 + FY2025 − H1 2025 = скользящий год, а не сумма полугодий."""
    _add_report(db, company, year=2025, period=PeriodType.SEMI_ANNUAL, month_end=6, net_income=400.0)
    _add_report(db, company, year=2025, net_income=1_000.0)
    _add_report(db, company, year=2026, period=PeriodType.SEMI_ANNUAL, month_end=6, net_income=500.0)

    ltm = get_ltm_data(db, company.id, as_of=date(2030, 1, 1))

    assert ltm["source"] == "semi_annual_derived"
    assert ltm["ltm_net_income"] == 1_100.0  # 500 + 1000 − 400


def test_nine_months_report_uses_interim_formula(db, company):
    """9 месяцев МСФО (ЛУКОЙЛ и подобные) — Q3 с накопительным итогом.

    LTM = 9М_2026 + FY2025 − 9М_2025, то есть октябрь 2025 – сентябрь 2026.
    """
    _add_report(db, company, year=2025, period=PeriodType.QUARTERLY, quarter=3, month_end=9, net_income=300.0)
    _add_report(db, company, year=2025, net_income=1_000.0)
    _add_report(db, company, year=2026, period=PeriodType.QUARTERLY, quarter=3, month_end=9, net_income=450.0)

    ltm = get_ltm_data(db, company.id, as_of=date(2030, 1, 1))

    assert ltm["source"] == "quarterly_3_derived"
    assert ltm["ltm_net_income"] == 1_150.0  # 450 + 1000 − 300


def test_interim_formula_ignores_reports_of_another_standard(db, company):
    """РСБУ-годовой не подставляется в формулу к МСФО-полугодию: базы разные."""
    _add_report(db, company, year=2025, period=PeriodType.SEMI_ANNUAL, month_end=6, net_income=400.0)
    _add_report(db, company, year=2025, net_income=1_000.0, accounting_standard=AccountingStandard.RAS)
    _add_report(db, company, year=2026, period=PeriodType.SEMI_ANNUAL, month_end=6, net_income=500.0)

    ltm = get_ltm_data(db, company.id, as_of=date(2030, 1, 1))

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

    ltm = get_ltm_data(db, company.id, as_of=date(2030, 1, 1))

    assert ltm["source"] == "annual"
    assert ltm["ltm_net_income"] == 1_000.0


def test_ytd_for_four_quarters_is_taken_as_full_year(db, company):
    """YTD за 4 квартала — это уже год: берём отчёт целиком, ничего не складывая."""
    for quarter, month, profit in ((1, 3, 100.0), (3, 9, 400.0), (4, 12, 600.0)):
        _add_report(
            db, company, year=2026, period=PeriodType.QUARTERLY,
            quarter=quarter, month_end=month, net_income=profit,
        )

    ltm = get_ltm_data(db, company.id, as_of=date(2030, 1, 1))

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

    ltm = get_ltm_data(db, company.id, as_of=date(2030, 1, 1))

    assert ltm["source"] == "annual"
    assert ltm["ltm_net_income"] == 1_000.0


def test_ytd_reports_are_never_summed_with_each_other(db, company):
    """Только 3М и 9М без годового — LTM не считается, а не складывается.

    3М + 9М даёт формально 12 месяцев, но первый квартал в этой сумме учтён
    дважды, а четвёртый не учтён вовсе. Пустой мультипликатор честнее.
    """
    _add_report(db, company, year=2026, period=PeriodType.QUARTERLY, quarter=1, month_end=3, net_income=100.0)
    _add_report(db, company, year=2026, period=PeriodType.QUARTERLY, quarter=3, month_end=9, net_income=400.0)

    ltm = get_ltm_data(db, company.id, as_of=date(2030, 1, 1))

    assert ltm["source"] == "insufficient"
    assert ltm["ltm_net_income"] is None
    assert ltm["balance_report"].fiscal_quarter == 3  # баланс всё равно свежий


# ─── Дивиденды, банки, пустая база ───────────────────────────────────────────


def test_dividends_not_paid_do_not_leak_into_ltm(db, company):
    """Дивиденд из отчёта, где выплат не было, в LTM не попадает."""
    _add_report(db, company, year=2025, net_income=1_000.0, dividends_per_share=None)

    ltm = get_ltm_data(db, company.id, as_of=date(2030, 1, 1))

    assert ltm["ltm_dividends_per_share"] is None


def test_dividend_is_brought_to_post_split_scale(db, company):
    """Дивиденд до дробления приводится к сегодняшней шкале.

    Случай Т-Технологий: за 2025 год объявлено 149 ₽ на акцию, в апреле 2026
    прошло дробление 10:1, и текущая цена — уже 261 ₽ за десятую долю прежней
    бумаги. Сложить их напрямую значит показать доходность 57% вместо 5,7%.
    Запись в базе остаётся прежней: приводим только в момент расчёта.
    """
    _add_report(db, company, year=2025, net_income=1_000.0,
                dividends_per_share=149.0)
    company.share_splits = [{"date": "2026-04-17", "ratio": 10}]
    db.commit()

    ltm = get_ltm_data(db, company.id, as_of=date(2030, 1, 1))

    assert ltm["ltm_dividends_per_share"] == pytest.approx(14.9)


def test_dividend_after_split_is_left_alone(db, company):
    """Отчёт, вышедший ПОСЛЕ дробления, уже в сегодняшней шкале."""
    _add_report(db, company, year=2026, net_income=1_000.0,
                dividends_per_share=15.0)
    company.share_splits = [{"date": "2026-04-17", "ratio": 10}]
    db.commit()

    ltm = get_ltm_data(db, company.id, as_of=date(2030, 1, 1))

    assert ltm["ltm_dividends_per_share"] == pytest.approx(15.0)


def test_bank_fields_are_aggregated_for_bank_reports(db, company):
    """Для банка к потоку добавляются процентные и комиссионные доходы."""
    _add_report(
        db, company, year=2025, net_income=1_000.0,
        report_type="bank", net_interest_income=800.0,
    )

    ltm = get_ltm_data(db, company.id, as_of=date(2030, 1, 1))

    assert ltm["ltm_net_interest_income"] == 800.0


def test_hybrid_report_aggregates_bank_fields_too(db, company):
    """Гибриду финсегмент нужен, хотя тип отчёта у него общий.

    У Яндекса банк живёт внутри обычной отчётности: `report_type` остаётся
    general, но портфель и резервы заполнены. Раньше агрегация смотрела на
    тип отчёта и такие поля отбрасывала.
    """
    _add_report(db, company, year=2025, net_income=1_000.0, net_interest_income=800.0)

    ltm = get_ltm_data(db, company.id, as_of=date(2030, 1, 1))

    assert ltm["ltm_net_interest_income"] == 800.0


def test_industrial_report_has_no_bank_flows(db, company):
    """У промышленной компании банковских полей нет — и в LTM их не появится."""
    _add_report(db, company, year=2025, net_income=1_000.0)

    ltm = get_ltm_data(db, company.id, as_of=date(2030, 1, 1))

    assert ltm["ltm_net_interest_income"] is None
    assert ltm["ltm_provisions"] is None


def test_company_without_reports_returns_none(db, company):
    assert get_ltm_data(db, company.id, as_of=date(2030, 1, 1)) is None


@pytest.mark.parametrize('quarter,month,label', [(1, 3, '1К'), (2, 6, '1П'), (3, 9, '9М')])
def test_valuation_ltm_uses_quarterly_ytd(db, company, quarter, month, label):
    from app.services.analysis.earning_power import YearPoint, with_ltm

    fy = _add_report(db, company, year=2025, net_income=100)
    prior = _add_report(db, company, year=2025, period=PeriodType.QUARTERLY,
                        quarter=quarter, month_end=month, net_income=20)
    current = _add_report(db, company, year=2026, period=PeriodType.QUARTERLY,
                          quarter=quarter, month_end=month, net_income=35, equity=500)
    for r, profit, ocf, capex, depreciation in (
        (fy, 100, 120, 30, 10), (prior, 20, 25, 5, 2), (current, 35, 40, 8, 3),
    ):
        r.net_income_reported = profit
        r.operating_cash_flow = ocf
        r.capex = capex
        r.depreciation_amortization = depreciation
    db.commit()
    points = [YearPoint(year=2025, eps=100, shares_normalized=1_000_000)]
    rolled = with_ltm(db, company.id, points, date(2026, 12, 1))
    assert len(rolled) == len(points)
    assert rolled[-1].year == 2025
    assert rolled[-1].ltm_label == f'LTM {label}2026'
    assert rolled[-1].eps == 115
    assert rolled[-1].fcf_per_share == 102  # (120+40−25) − (30+8−5)
    assert rolled[-1].book_value_per_share == 500
    assert points[-1].eps == 100
    # Текущие мультипликаторы и ряд оценки используют одну YTD-формулу.
    assert get_ltm_data(db, company.id, as_of=date(2030, 1, 1))['ltm_net_income'] == 115


def _valuation_interims(db, company):
    from app.services.analysis.earning_power import YearPoint
    fy = _add_report(db, company, year=2025, net_income=100)
    h1_old = _add_report(db, company, year=2025, period=PeriodType.SEMI_ANNUAL,
                         month_end=6, net_income=40)
    h1 = _add_report(db, company, year=2026, period=PeriodType.SEMI_ANNUAL,
                     month_end=6, net_income=50)
    q3 = _add_report(db, company, year=2026, period=PeriodType.QUARTERLY,
                     quarter=3, month_end=9, net_income=90)
    for r in (fy, h1_old, h1, q3):
        r.net_income_reported = r.net_income
    q3.filing_date = date(2026, 11, 10)
    db.commit()
    return [YearPoint(year=2025, eps=100, fcf_per_share=70, shares_normalized=1_000_000)], fy, q3


def test_quarterly_valuation_falls_back_to_h1_until_disclosure(db, company):
    from app.services.analysis.earning_power import with_ltm
    points, fy, q3 = _valuation_interims(db, company)
    q3.comparative = {'net_income_reported': 60, 'net_income': 60}
    db.commit()
    before = with_ltm(db, company.id, points, date(2026, 11, 9))[-1]
    after = with_ltm(db, company.id, points, date(2026, 11, 10))[-1]
    assert before.ltm_label == 'LTM 1П2026' and before.eps == 110
    assert after.ltm_label == 'LTM 9М2026' and after.eps == 130
    assert after.fcf_per_share == 70  # неполный ОДДС не обнуляет годовой FCF


def test_quarterly_valuation_missing_pair_uses_h1(db, company):
    from app.services.analysis.earning_power import with_ltm
    points, fy, q3 = _valuation_interims(db, company)
    result = with_ltm(db, company.id, points, date(2026, 12, 1))[-1]
    assert result.ltm_label == 'LTM 1П2026' and result.eps == 110


@pytest.mark.parametrize('mismatch', ['standard', 'consolidated', 'future_fy'])
def test_quarterly_valuation_requires_comparable_disclosed_annual(db, company, mismatch):
    from app.services.analysis.earning_power import with_ltm
    points, fy, q3 = _valuation_interims(db, company)
    if mismatch == 'standard':
        fy.accounting_standard = AccountingStandard.RAS
    elif mismatch == 'consolidated':
        fy.consolidated = False
    else:
        fy.disclosed_at = date(2027, 1, 1)
    db.commit()
    assert with_ltm(db, company.id, points, date(2026, 12, 1)) is points


def test_quarter_disclosure_defaults_and_actual_dates():
    from types import SimpleNamespace
    from app.utils.disclosure import disclosed_on, period_end
    from datetime import timedelta

    for q, end in [(1, date(2026, 3, 31)), (2, date(2026, 6, 30)),
                   (3, date(2026, 9, 30)), (4, date(2026, 12, 31))]:
        report = SimpleNamespace(fiscal_year=2026, period_type=PeriodType.QUARTERLY,
                                 fiscal_quarter=q, report_date=end)
        assert period_end(2026, PeriodType.QUARTERLY, q) == end
        assert disclosed_on(report) == end + timedelta(days=60)
        report.filing_date = end + timedelta(days=40)
        assert disclosed_on(report) == report.filing_date
        report.disclosed_at = end + timedelta(days=25)
        assert disclosed_on(report) == report.disclosed_at


def test_quarterly_disclosure_creates_valuation_chart_step(db, company, monkeypatch):
    from datetime import timedelta
    from types import SimpleNamespace
    from app.services.analysis import valuation_backtest as vb
    from app.services.analysis import earning_power as ep

    points, fy, q3 = _valuation_interims(db, company)
    q3.comparative = {'net_income_reported': 60, 'net_income': 60}
    db.commit()
    monkeypatch.setattr(vb, 'load_points', lambda *args, **kwargs: points)
    # Проверяем настоящую сборку LTM и события графика, заменяя лишь модель
    # капитализации: новая прибыль должна попасть в опорную в день раскрытия.
    def models(db, company, window=7, points=None):
        value = points[-1].eps
        band = SimpleNamespace(refused=False, reason=None, low=value, high=value,
                               conservative=value, method='cottle', ladders=[])
        return [(2025, 1.0, lambda *args, **kwargs: band)]
    monkeypatch.setattr(vb, 'year_models', models)
    monkeypatch.setattr(ep, '_cash_parts', lambda *args: None)
    rates = SimpleNamespace(trailing=lambda day: 15.0)
    out = vb.valuation_segments(db, company, 5, rates, today_rate=15,
                                today=date(2026, 11, 17), lag=timedelta(days=120))
    q3_steps = [r for r in out if r['basis'] == 'LTM 9М2026']
    assert q3_steps[0]['from'] == '2026-11-10'
    assert q3_steps[-1]['reference'] == 130
    assert all(r['basis'] != 'LTM 9М2026' for r in out if r['from'] < '2026-11-10')
    assert any(r['basis'] == 'LTM 1П2026' for r in out)


def test_current_and_valuation_wait_for_quarter_disclosure(db, company):
    from app.services.analysis.earning_power import with_ltm
    points, fy, q3 = _valuation_interims(db, company)
    q3.comparative = {'net_income_reported': 60, 'net_income': 60}
    q3.filing_date = None
    db.commit()
    for day, label, source, expected in [
        (date(2026, 11, 17), 'LTM 1П2026', 'semi_annual_derived', 110),
        (date(2026, 11, 29), 'LTM 9М2026', 'quarterly_3_derived', 130),
    ]:
        current = get_ltm_data(db, company.id, as_of=day)
        rolled = with_ltm(db, company.id, points, day)[-1]
        assert current['source'] == source
        assert current['ltm_net_income'] == expected == rolled.eps
        assert rolled.ltm_label == label
    # Фактическая дата приоритетнее запасного лага.
    q3.disclosed_at = date(2026, 11, 10)
    db.commit()
    current = get_ltm_data(db, company.id, as_of=date(2026, 11, 17))
    assert current['source'] == 'quarterly_3_derived'
    assert current['ltm_net_income'] == 130


def test_current_ltm_does_not_use_unpublished_fy(db, company):
    points, fy, q3 = _valuation_interims(db, company)
    fy.disclosed_at = date(2027, 1, 1)
    db.commit()
    result = get_ltm_data(db, company.id, as_of=date(2026, 11, 17))
    assert result['source'] == 'insufficient'
    assert result['ltm_net_income'] is None
