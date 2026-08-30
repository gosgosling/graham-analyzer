"""Очистка свободного потока гибрида от встроенного банка.

Цифры — из отчёта Яндекса за 2025 год: операционный поток 282,3 млрд, прирост
средств клиентов 148,9 млрд, прирост кредитов клиентам 71,9 млрд, capex
145,9 млрд, погашение тела аренды 18,1 млрд. Дивиденды за тот же год —
60,5 млрд, и именно сопоставление с ними показывает, откуда они платятся.
"""
from types import SimpleNamespace

import pytest

from app.services.analysis.fcf import compute_banking_flow, compute_core_fcf, compute_fcf


def _period(
    deposits=None, loans=None, cf_deposits=None, cf_loans=None, cf_other=None
) -> SimpleNamespace:
    """Отчёт-заглушка: остатки баланса и, отдельно, строки ОДДС."""
    return SimpleNamespace(
        customer_deposits=deposits,
        gross_loans=loans,
        cf_customer_deposits=cf_deposits,
        cf_customer_loans=cf_loans,
        cf_other_float=cf_other,
    )


def test_cash_flow_lines_are_preferred_source():
    """Строки ОДДС — фактическое движение денег, у Яндекса это 77 млрд.

    Именно так: +148 939 приток средств клиентов и −71 943 выдача кредитов,
    переписанные из отчёта со знаком.
    """
    flow, basis = compute_banking_flow(_period(cf_deposits=148_939, cf_loans=-71_943))

    assert flow == pytest.approx(76_996)
    assert basis == "cash_flow"


def test_balance_deltas_are_fallback_and_overstate_the_flow():
    """Без строк ОДДС считаем по остаткам — и честно называем основание.

    Разница остатков завышает приток: в неё попадают секьюритизация и
    списания, не проходящие через денежный поток. У Яндекса 100 против 77.
    """
    flow, basis = compute_banking_flow(
        _period(deposits=267_470, loans=145_962),
        _period(deposits=108_056, loans=86_517),
    )

    assert flow == pytest.approx(99_969)
    assert basis == "balance_delta"


def test_cash_flow_wins_over_balance_deltas():
    """Если есть и то, и другое — берём ОДДС."""
    flow, basis = compute_banking_flow(
        _period(deposits=267_470, loans=145_962, cf_deposits=148_939, cf_loans=-71_943),
        _period(deposits=108_056, loans=86_517),
    )

    assert flow == pytest.approx(76_996)
    assert basis == "cash_flow"


def test_core_fcf_matches_the_report():
    """Яндекс 2025: 282 330 − 76 996 − 145 868 − 18 117 = 41 349 млн.

    При дивидендах 60 492 млн выплата больше свободного потока ядра — вывод,
    которого в сыром FCF не видно.
    """
    reported_fcf = compute_fcf(282_330, 145_868, lease_principal=18_117)
    banking_flow, _ = compute_banking_flow(_period(cf_deposits=148_939, cf_loans=-71_943))

    core = compute_core_fcf(reported_fcf, banking_flow)

    assert reported_fcf == pytest.approx(118_345)   # сырой поток втрое больше
    assert core == pytest.approx(41_349)


def test_no_source_at_all_means_no_cleaned_flow():
    """Ни строк ОДДС, ни соседнего года — показывать нечего."""
    assert compute_banking_flow(_period(deposits=520_000), None) == (None, None)
    assert compute_core_fcf(118_300, None) is None


def test_single_report_is_enough_with_cash_flow_lines():
    """Со строками ОДДС соседний период не нужен — работает на первом же годе."""
    flow, basis = compute_banking_flow(_period(cf_deposits=148_939, cf_loans=-71_943), None)

    assert flow == pytest.approx(76_996)
    assert basis == "cash_flow"


def test_missing_segment_fields_disable_cleaning():
    """Ничего не выписано из отчёта — очищенный поток не выдумываем."""
    assert compute_banking_flow(_period(), _period()) == (None, None)


def test_only_deposit_line_is_still_usable():
    """Выписана одна строка ОДДС — считаем по ней.

    Оценка консервативнее сырого потока: вычитается весь приток депозитов
    без встречной выдачи кредитов.
    """
    flow, basis = compute_banking_flow(_period(cf_deposits=148_939))

    assert flow == pytest.approx(148_939)
    assert basis == "cash_flow"


def test_deposit_outflow_increases_core_flow():
    """Отток депозитов уменьшает отчётный поток — ядро, наоборот, сильнее."""
    flow, _ = compute_banking_flow(_period(cf_deposits=-71_100, cf_loans=0))

    assert flow < 0
    assert compute_core_fcf(50_000, flow) > 50_000


# ─── Подключение к расчёту мультипликаторов (нужна база) ─────────────────────

from datetime import date  # noqa: E402

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.database import Base  # noqa: E402
from app.models import Company, FinancialReport  # noqa: E402
from app.models.enums import PeriodType, ReportSource  # noqa: E402
from app.services.analysis.multiplier_service import calculate_current_multipliers  # noqa: E402


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def _yandex_like(db, company_type: str):
    """Компания с двумя годовыми отчётами: 2024 и 2025 со встроенным банком."""
    company = Company(
        figi="F", ticker="YDEX", name="Гибрид", currency="RUB",
        sector="it", company_type=company_type,
    )
    db.add(company)
    db.commit()

    def report(year, deposits, loans, ocf, capex, cf_deposits=None, cf_loans=None):
        return FinancialReport(
            company_id=company.id, period_type=PeriodType.ANNUAL, fiscal_year=year,
            accounting_standard="IFRS", consolidated=True, report_date=date(year, 12, 31),
            source=ReportSource.MANUAL, report_type="general", currency="RUB",
            price_per_share=4000, shares_outstanding=380_800_000,
            net_income=79_600, equity=400_000, revenue=1_200_000,
            operating_cash_flow=ocf, capex=capex, lease_principal=18_117,
            customer_deposits=deposits, gross_loans=loans,
            cf_customer_deposits=cf_deposits, cf_customer_loans=cf_loans,
        )

    db.add(report(2024, 108_056, 86_517, 203_185, 124_624, cf_deposits=81_070, cf_loans=-60_346))
    db.add(report(2025, 267_470, 145_962, 282_330, 145_868, cf_deposits=148_939, cf_loans=-71_943))
    db.commit()
    return company


def test_hybrid_gets_cleaned_flow_alongside_reported(db):
    company = _yandex_like(db, "hybrid")

    result = calculate_current_multipliers(db, company.id)

    assert result["banking_flow"] == pytest.approx(76_996)
    assert result["banking_flow_basis"] == "cash_flow"
    # Сырой FCF втрое больше очищенного — та самая разница, которую видно
    # только после вычета притока чужих денег.
    assert result["ltm_fcf"] == pytest.approx(118_345)
    assert result["ltm_core_fcf"] == pytest.approx(41_349)


def test_industrial_company_has_no_cleaning(db):
    """Обычной компании очищать нечего — поля пустые, а не равны сырым."""
    company = _yandex_like(db, "industrial")

    result = calculate_current_multipliers(db, company.id)

    assert result["banking_flow"] is None
    assert result["ltm_core_fcf"] is None
    assert result["ltm_fcf"] is not None


# ─── Второй пул чужих денег ────────────────────────────────────────────────
#
# У Озона рядом с депозитами Финтеха живут обязательства перед продавцами
# маркетплейса: покупатель заплатил, продавцу ещё не перечислили. На балансе
# за 2025 год это 339 786 млн против 505 788 млн депозитов — сопоставимо.
# Прирост такого флоата надувает операционный поток ровно как прирост
# депозитов, поэтому входит в приток третьим слагаемым.
#
# Цифры из отчёта Озона за 2025: операционный поток 503 629, capex 58 164,
# тело аренды 27 183, средства клиентов +362 728, кредиты клиентам -46 519,
# обязательства перед продавцами +89 854.


def test_marketplace_float_joins_banking_flow():
    flow, basis = compute_banking_flow(
        _period(cf_deposits=362_728, cf_loans=-46_519, cf_other=89_854)
    )

    assert flow == 406_063.0
    assert basis == "cash_flow"


def test_core_fcf_without_marketplace_float_is_overstated():
    """Забыть про деньги продавцов — завысить собственный поток в восемь раз."""
    fcf = compute_fcf(503_629, 58_164, 27_183)
    assert fcf == 418_282.0

    only_fintech, _ = compute_banking_flow(_period(cf_deposits=362_728, cf_loans=-46_519))
    both, _ = compute_banking_flow(
        _period(cf_deposits=362_728, cf_loans=-46_519, cf_other=89_854)
    )

    assert compute_core_fcf(fcf, only_fintech) == 102_073.0
    assert compute_core_fcf(fcf, both) == 12_219.0


def test_other_float_alone_is_enough_for_cash_flow_basis():
    """Компании без банка, но с флоатом: депозитов нет, а поток чистить надо."""
    flow, basis = compute_banking_flow(_period(cf_other=89_854))

    assert flow == 89_854.0
    assert basis == "cash_flow"


def test_empty_other_float_keeps_previous_behaviour():
    """У Яндекса и Мосбиржи поле пустое — приток считается как раньше."""
    flow, _ = compute_banking_flow(_period(cf_deposits=148_939, cf_loans=-71_943))

    assert flow == 76_996.0
