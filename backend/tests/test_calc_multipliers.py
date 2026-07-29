"""Мультипликаторы: арифметика и ветвление general / bank.

Базовый отчёт из conftest подобран так, чтобы ответы были круглыми:
капитализация 100 млрд ₽, прибыль 10 млрд, капитал 50 млрд →
P/E = 10, P/B = 2, ROE = 20%, D/E = 0.5, Current Ratio = 2.
"""
import pytest

from app.services.analysis.calc_multipliers import calculate_multipliers


def test_base_ratios(report):
    m = calculate_multipliers(report)

    assert m["market_cap"] == 100_000.0  # млн ₽
    assert m["pe_ratio"] == 10.0
    assert m["pb_ratio"] == 2.0
    assert m["roe"] == 20.0
    assert m["debt_to_equity"] == 0.5
    assert m["current_ratio"] == 2.0
    assert m["shares_used"] == 1_000_000_000


def test_overrides_win_over_report(report):
    m = calculate_multipliers(report, override_price=200.0, override_shares=500_000_000)

    assert m["market_cap"] == 100_000.0
    assert m["price_used"] == 200.0
    assert m["shares_used"] == 500_000_000


def test_ltm_values_win_over_report(report):
    m = calculate_multipliers(report, ltm_net_income=20_000.0)

    assert m["pe_ratio"] == 5.0
    assert m["roe"] == 40.0


def test_loss_gives_no_pe(report_factory):
    """При убытке P/E не имеет смысла, а ROE обязан остаться отрицательным."""
    m = calculate_multipliers(report_factory(net_income=-5_000.0))

    assert m["pe_ratio"] is None
    assert m["roe"] == -10.0


def test_negative_equity_gives_no_pb(report_factory):
    m = calculate_multipliers(report_factory(equity=-1_000.0))

    assert m["pb_ratio"] is None
    assert m["debt_to_equity"] == -25.0


def test_missing_price_gives_no_market_metrics(report_factory):
    m = calculate_multipliers(report_factory(price_per_share=None))

    assert m["market_cap"] is None
    assert m["pe_ratio"] is None
    assert m["pb_ratio"] is None
    assert m["dividend_yield"] is None
    # Не зависящие от цены показатели должны считаться как обычно.
    assert m["roe"] == 20.0
    assert m["current_ratio"] == 2.0


# ─── Дивиденды ──────────────────────────────────────────────────────────────


def test_dividend_yield_without_special_part(report):
    m = calculate_multipliers(report)

    assert m["dividend_yield"] == 6.0
    # Разовая часть не размечена → регулярная доходность равна общей.
    assert m["dividend_yield_regular"] == 6.0


def test_special_part_lowers_regular_yield(report_factory):
    """20 ₽ дивиденда, из них 12 ₽ разовых → регулярная доходность 8 ₽ / 100 ₽."""
    m = calculate_multipliers(
        report_factory(dividends_per_share=20.0, special_dividends_per_share=12.0)
    )

    assert m["dividend_yield"] == 20.0
    assert m["dividend_yield_regular"] == 8.0
    assert m["ltm_special_dividends_per_share"] == 12.0


def test_special_part_never_makes_yield_negative(report_factory):
    """Разовая часть больше общей суммы — данные битые, но в минус уходить нельзя."""
    m = calculate_multipliers(
        report_factory(dividends_per_share=10.0, special_dividends_per_share=25.0)
    )

    assert m["dividend_yield"] == 10.0
    assert m["dividend_yield_regular"] == 0.0


def test_no_dividends_paid_means_no_yield(report_factory):
    """Сумма в отчёте осталась с прошлого года, но выплат не было."""
    m = calculate_multipliers(
        report_factory(dividends_paid=False, dividends_per_share=6.0)
    )

    assert m["dividend_yield"] is None
    assert m["dividend_yield_regular"] is None


def test_ltm_dividends_win_over_report(report_factory):
    m = calculate_multipliers(
        report_factory(dividends_per_share=6.0),
        ltm_dividends_per_share=15.0,
        ltm_special_dividends_per_share=5.0,
    )

    assert m["dividend_yield"] == 15.0
    assert m["dividend_yield_regular"] == 10.0


# ─── FCF ────────────────────────────────────────────────────────────────────


def test_fcf_chain(report):
    """FCF = OCF 15 000 − CAPEX 5 000 = 10 000 млн; P/FCF = 100 000 / 10 000."""
    m = calculate_multipliers(report)

    assert m["ltm_fcf"] == 10_000.0
    assert m["price_to_fcf"] == 10.0
    assert m["fcf_to_net_income"] == 1.0
    assert m["net_debt"] == 15_000.0  # долг 20 000 − деньги 5 000
    assert m["net_debt_to_fcf"] == 1.5


def test_lease_and_interest_paid_reduce_fcf_but_debt_principal_does_not(report_factory):
    """Аренда и проценты уплаченные вычитаются; тело долга — нет."""
    m = calculate_multipliers(
        report_factory(
            lease_principal=2_000.0,
            lease_interest=500.0,
            interest_paid=1_000.0,
            debt_principal=1_500.0,
        )
    )

    # OCF 15_000 − CAPEX 5_000 − lease 2_000 − lease% 500 − interest 1_000 = 6_500
    assert m["ltm_fcf"] == 6_500.0
    assert m["fcf_to_net_income"] == 0.65


def test_negative_fcf_gives_no_price_to_fcf(report_factory):
    m = calculate_multipliers(report_factory(operating_cash_flow=3_000.0, capex=8_000.0))

    assert m["ltm_fcf"] == -5_000.0
    assert m["price_to_fcf"] is None
    # Отношение к прибыли остаётся: отрицательный FCF при прибыли — важный сигнал.
    assert m["fcf_to_net_income"] == -0.5


def test_missing_capex_blocks_fcf(report_factory):
    m = calculate_multipliers(report_factory(capex=None))

    assert m["ltm_fcf"] is None
    assert m["price_to_fcf"] is None
    assert m["net_debt_to_fcf"] is None


# ─── Банк ───────────────────────────────────────────────────────────────────


def test_bank_skips_leverage_and_liquidity(report_factory):
    """У банка депозиты — обязательства по природе, D/E и CR не считаем."""
    m = calculate_multipliers(
        report_factory(
            report_type="bank",
            total_liabilities=325_000.0,
            equity=50_000.0,
            current_assets=None,
            current_liabilities=None,
            operating_expenses=20_000.0,
            revenue=50_000.0,
        )
    )

    assert m["debt_to_equity"] is None
    assert m["current_ratio"] is None
    assert m["cost_to_income"] == 40.0  # 20 000 / 50 000
    # FCF для банка концептуально неприменим.
    assert m["ltm_fcf"] is None
    assert m["price_to_fcf"] is None
    # А стоимостные метрики считаются как обычно.
    assert m["pe_ratio"] == 10.0
    assert m["pb_ratio"] == 2.0


def test_bank_cir_uses_ltm_revenue(report_factory):
    m = calculate_multipliers(
        report_factory(report_type="bank", operating_expenses=20_000.0, revenue=50_000.0),
        ltm_revenue=40_000.0,
    )

    assert m["cost_to_income"] == 50.0


# ─── Валюта отчёта ──────────────────────────────────────────────────────────


def test_usd_report_converted_by_exchange_rate(report_factory):
    """Отчёт в USD: цена и денежные поля приводятся к рублям одним курсом,
    поэтому безразмерные отношения не должны измениться."""
    usd = report_factory(currency="USD", exchange_rate=90.0)
    rub = report_factory()

    m_usd = calculate_multipliers(usd)
    m_rub = calculate_multipliers(rub)

    assert m_usd["pe_ratio"] == m_rub["pe_ratio"]
    assert m_usd["pb_ratio"] == m_rub["pb_ratio"]
    assert m_usd["dividend_yield"] == m_rub["dividend_yield"]
    # Капитализация же вырастает в 90 раз — она в рублях.
    assert m_usd["market_cap"] == m_rub["market_cap"] * 90
    assert m_usd["price_used"] == 9_000.0


def test_eur_report_uses_exchange_rate_too(report_factory):
    """Раньше конвертировался только USD — EUR/CNY тихо оставались «как есть»."""
    eur = report_factory(currency="EUR", exchange_rate=100.0)
    rub = report_factory()

    m_eur = calculate_multipliers(eur)
    m_rub = calculate_multipliers(rub)

    assert m_eur["pe_ratio"] == m_rub["pe_ratio"]
    assert m_eur["market_cap"] == m_rub["market_cap"] * 100
    assert m_eur["price_used"] == 10_000.0


def test_penny_stock_keeps_price_and_ratios(report_factory):
    """Копеечная бумага (ТГК-1: 0,004365 ₽ × 1,458 трлн акций).

    При округлении цены до двух знаков капитализация и P/E обнулялись —
    в этом классе бумаг округление всегда играет против нас.
    """
    penny = report_factory(
        price_per_share=0.004365,
        shares_outstanding=1_458_404_850_747,
        net_income=3_580.573,   # млн ₽
        equity=20_628.875,      # млн ₽
        dividends_per_share=0.000345,
    )

    m = calculate_multipliers(penny)

    assert m["price_used"] == 0.004365
    # 0,004365 × 1,4584 трлн ≈ 6,366 млрд ₽
    assert m["market_cap"] == pytest.approx(6_365.9, rel=1e-3)
    assert m["pe_ratio"] == pytest.approx(1.78, abs=0.01)
    assert m["pb_ratio"] == pytest.approx(0.31, abs=0.01)
    assert m["dividend_yield"] == pytest.approx(7.9, abs=0.1)
