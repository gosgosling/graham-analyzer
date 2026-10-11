"""Касса отдельно от бизнеса — вариант Грэма для компаний с чистой кассой.

Базовый отчёт из conftest переделан под чистую кассу: денег 30 000, долга
10 000 → чистая касса 20 000 млн, капитализация 100 000, FCF 10 000.
"""
import pytest

from app.services.analysis import cash_income
from app.services.analysis.calc_multipliers import calculate_multipliers
from app.services.analysis.company_valuation import Ladder, ValueBand, add_net_cash
from app.services.analysis.earning_power import (
    YearPoint, _cash_parts, graham_numbers, latest_book_value, retention_test,
)


def _cash_rich(report_factory, **overrides):
    values = dict(cash_and_equivalents=30_000.0, debt=10_000.0)
    values.update(overrides)
    return report_factory(**values)


# ─── Правило ────────────────────────────────────────────────────────────────


def test_ставка_налога_по_году():
    assert cash_income.tax_rate(2024) == 0.20
    assert cash_income.tax_rate(2025) == 0.25


def test_чистая_касса_не_бывает_отрицательной():
    assert cash_income.net_cash(30_000, 10_000) == 20_000
    assert cash_income.net_cash(5_000, 20_000) == 0
    assert cash_income.net_cash(None, 1) is None


@pytest.mark.parametrize("kind", ["bank", "exchange", "hybrid", "insurance", "COMPANY_LENDER"])
def test_клиентские_деньги_не_отделяются(report_factory, kind):
    report = _cash_rich(report_factory, interest_received=2_000.0)
    assert not cash_income.separates(report, kind)


def test_без_заведённых_процентов_правило_молчит(report_factory):
    """Пустое поле — «не разносили»: вычесть кассу из цены, не убрав доход
    от неё из прибыли, значит учесть её дважды."""
    assert not cash_income.separates(_cash_rich(report_factory))
    assert cash_income.separates(_cash_rich(report_factory, interest_received=0.0))


def test_при_чистом_долге_касса_не_отделяется(report_factory):
    assert not cash_income.separates(report_factory(interest_received=500.0))


# ─── P/FCF ──────────────────────────────────────────────────────────────────


def test_pfcf_проценты_в_операционном_потоке(report_factory):
    """Цена бизнеса 100 000 − 20 000; поток бизнеса 10 000 − 2 000."""
    m = calculate_multipliers(_cash_rich(
        report_factory, interest_received=2_000.0, interest_received_in_ocf=True,
    ))
    assert m["business_price"] == 80_000.0
    assert m["business_fcf"] == 8_000.0
    assert m["price_to_fcf"] == 10.0
    # Сам FCF не трогаем: это отчётная величина, её видит вся страница.
    assert m["ltm_fcf"] == 10_000.0


def test_pfcf_проценты_в_инвестиционном_потоке(report_factory):
    """Из потока вычитать нечего — процентов в нём и не было."""
    m = calculate_multipliers(_cash_rich(
        report_factory, interest_received=2_000.0, interest_received_in_ocf=False,
    ))
    assert m["business_fcf"] == 10_000.0
    assert m["price_to_fcf"] == 8.0


def test_pfcf_без_процентов_прежний(report_factory):
    m = calculate_multipliers(_cash_rich(report_factory))
    assert m["price_to_fcf"] == 10.0
    assert m["business_price"] is None


def test_pfcf_у_банка_прежний(report_factory):
    m = calculate_multipliers(
        _cash_rich(report_factory, interest_received=2_000.0, interest_received_in_ocf=True),
        company_type="bank",
    )
    assert m["business_price"] is None


# ─── Ряд оценки ─────────────────────────────────────────────────────────────


def test_части_кассы_отчёта(report_factory):
    report = _cash_rich(report_factory, interest_received=2_000.0, interest_received_in_ocf=True)
    net, after_tax, in_flow = _cash_parts(report, None, 2025)
    assert net == 20_000.0
    assert after_tax == pytest.approx(1_500.0)  # 2 000 × (1 − 25%)
    assert in_flow == 2_000.0
    assert _cash_parts(_cash_rich(report_factory), None, 2025) is None


def test_капитал_бизнеса_без_кассы():
    points = [YearPoint(year=2025, book_value_per_share=50.0, net_cash_per_share=20.0)]
    assert latest_book_value(points) == 30.0
    assert latest_book_value(points, business=False) == 50.0
    # Касса больше капитала — у бизнеса капитала нет.
    rich = [YearPoint(year=2025, book_value_per_share=50.0, net_cash_per_share=60.0)]
    assert latest_book_value(rich) is None


def test_отчётная_арифметика_видит_доход_кассы():
    """Тест удержания и число Грэма — про отчётные числа."""
    points = [
        YearPoint(year=y, eps=8.0, cash_income_per_share=2.0,
                  dividends_per_share=5.0, book_value_per_share=50.0 + 5 * i)
        for i, y in enumerate((2023, 2024, 2025))
    ]
    assert points[0].reported_eps == 10.0
    assert retention_test(points, 3)["retained_per_share"] == 15.0
    assert graham_numbers(points)[2025] == pytest.approx((22.5 * 10 * 60) ** 0.5, abs=0.01)


def test_касса_прибавляется_к_полосе_рубль_за_рубль():
    band = ValueBand(
        low=80.0, high=120.0, low_by_earnings=80.0, high_by_earnings=120.0,
        conservative=70.0,
        ladders=[Ladder(name="прибыль", normal_per_share=8.0, multiple=15.0,
                        value=120.0, adjusted=None)],
    )
    add_net_cash(band, 20.0)
    assert (band.low, band.high, band.conservative) == (100.0, 140.0, 90.0)
    assert band.ladders[0].value == 140.0 and band.ladders[0].adjusted is None
    # Ширина — про бизнес, касса её не сужает.
    assert band.width == 1.5
    assert band.as_dict()["net_cash"] == 20.0


def test_отказ_кассой_не_лечится():
    band = ValueBand(refused=True, reason="нет данных")
    add_net_cash(band, 20.0)
    assert band.low is None and band.net_cash == 0.0


def test_проверка_активов_по_всей_компании_когда_касса_больше_капитала():
    """У HeadHunter касса больше капитала: капитал бизнеса отрицателен, и
    проверка активов по нему молча выпала бы. По всей компании — нет:
    (бизнес 3 000 + касса 300) против двойного баланса 600 срезается."""
    from app.services.analysis.company_valuation import value_band

    kwargs = dict(payout=50.0, roe=20.0, risk_free_rate=12.0, risk_premium=4.0,
                  normal_earnings={"прибыль": 400.0}, book_value_per_share=300.0)
    whole = value_band(**kwargs)
    split = value_band(**{**kwargs, "normal_earnings": {"прибыль": 380.0}},
                       net_cash_per_share=300.0)
    ladder = split.ladders[0]
    assert ladder.asset_note is not None
    total = ladder.value - 300.0
    expected = (total + 300.0) - 0.25 * ((total + 300.0) - 600.0)
    assert ladder.adjusted == pytest.approx(expected, abs=0.02)
    assert split.net_cash == 300.0
    assert whole.ladders[0].asset_note is not None


def test_депозиты_и_облигации_входят_в_кассу(report_factory):
    """Денег 5 000 при долге 20 000 — чистый долг. С облигациями на 25 000
    касса уже 10 000: процентный доход с них тоже вычтен из прибыли."""
    assert cash_income.net_cash(5_000, 20_000, 25_000) == 10_000
    report = report_factory(cash_investments=25_000.0, interest_received=2_000.0,
                            interest_received_in_ocf=False)
    assert cash_income.separates(report)
    m = calculate_multipliers(report)
    assert m["business_price"] == 90_000.0
    assert m["price_to_fcf"] == 9.0
