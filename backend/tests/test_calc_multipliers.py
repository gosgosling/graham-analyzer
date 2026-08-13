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


def test_bank_cir_uses_ltm_pair(report_factory):
    """CIR берёт LTM-выручку только вместе с LTM-расходами."""
    m = calculate_multipliers(
        report_factory(report_type="bank", operating_expenses=20_000.0, revenue=50_000.0),
        ltm_revenue=40_000.0,
        ltm_operating_expenses=16_000.0,
    )

    assert m["cost_to_income"] == 40.0


def test_bank_cir_falls_back_to_report_pair(report_factory):
    """Без LTM-расходов считаем по отчёту целиком, а не смешиваем периоды.

    Раньше LTM-выручка за год делилась на расходы из отчёта: у полугодового
    отчёта это занижало CIR вдвое — банк выглядел вдвое эффективнее ровно в
    момент выхода промежуточной отчётности.
    """
    m = calculate_multipliers(
        report_factory(report_type="bank", operating_expenses=20_000.0, revenue=50_000.0),
        ltm_revenue=40_000.0,
    )

    assert m["cost_to_income"] == 40.0  # 20 000 / 50 000, обе величины из отчёта


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


# ─── FCF-мультипликаторы гибрида ────────────────────────────────────────────


def test_hybrid_fcf_ratios_use_core_flow(report_factory):
    """Приток клиентских денег не должен удешевлять компанию по P/FCF.

    Цифры близки к Яндексу за 2025: поток 118 345 при банковском притоке
    76 996 — ядро зарабатывает 41 349, то есть втрое меньше.
    """
    report = report_factory(
        operating_cash_flow=282_330.0, capex=145_868.0, lease_principal=18_117.0,
        net_income=79_579.0, debt=360_215.0, cash_and_equivalents=250_210.0,
        price_per_share=4_582.5, shares_outstanding=380_783_546,
    )

    core = calculate_multipliers(report, banking_flow=76_996.0)
    gross = calculate_multipliers(report)

    assert core["ltm_fcf"] == 118_345.0          # поток по отчёту не подменяется
    assert core["ltm_core_fcf"] == 41_349.0
    assert core["fcf_basis"] == "core"

    # Все три отношения считаются от ядра, поэтому строже «валовых»
    assert core["price_to_fcf"] > gross["price_to_fcf"]
    assert core["net_debt_to_fcf"] > gross["net_debt_to_fcf"]
    assert core["fcf_to_net_income"] < gross["fcf_to_net_income"]
    assert core["fcf_to_net_income"] == round(41_349.0 / 79_579.0, 4)


def test_company_without_finance_segment_is_untouched(report_factory):
    """У промышленной компании banking_flow=None — расчёт прежний."""
    report = report_factory(
        operating_cash_flow=100_000.0, capex=40_000.0, net_income=50_000.0,
    )

    m = calculate_multipliers(report)

    assert m["fcf_basis"] == "reported"
    assert m["ltm_core_fcf"] is None
    assert m["price_to_fcf"] == round(
        m["market_cap"] * 1_000_000 / (60_000.0 * 1_000_000), 2
    )


def test_hybrid_without_cash_flow_lines_falls_back(report_factory):
    """Строки ОДДС не заполнены → банковский поток неизвестен.

    Тогда честнее считать по общему потоку, чем не показать ничего; признак
    `fcf_basis` даёт интерфейсу отличить это от очищенного расчёта.
    """
    report = report_factory(operating_cash_flow=100_000.0, capex=40_000.0)

    m = calculate_multipliers(report, banking_flow=None)

    assert m["fcf_basis"] == "reported"
    assert m["price_to_fcf"] is not None


# ─── Биржа ──────────────────────────────────────────────────────────────────


def test_exchange_skips_leverage_but_keeps_fcf(report_factory):
    """У биржи обязательства — чужие деньги, но свободный поток свой.

    Цифры порядка МОЕХ за 2025: активы 13 трлн, из них 10,2 трлн — зеркальные
    позиции центрального контрагента, свой капитал 0,27 трлн. D/E вышел бы 47×,
    и это способ учёта, а не плечо.
    """
    m = calculate_multipliers(
        report_factory(
            report_type="exchange",
            total_liabilities=12_758_250.0,
            equity=269_061.0,
            current_assets=None,
            current_liabilities=None,
            operating_expenses=30_000.0,
            revenue=100_000.0,
            operating_cash_flow=80_000.0,
            capex=12_000.0,
        )
    )

    # Плечо и ликвидность отключены, как у банка
    assert m["debt_to_equity"] is None
    assert m["current_ratio"] is None
    # Эффективность считается
    assert m["cost_to_income"] == 30.0
    # А FCF — в отличие от банка — остаётся
    assert m["ltm_fcf"] == 68_000.0
    assert m["price_to_fcf"] is not None


def test_exchange_fcf_ratios_use_core_flow(report_factory):
    """Приток средств участников торгов вычищается так же, как у гибрида."""
    report = report_factory(
        report_type="exchange", operating_cash_flow=80_000.0, capex=12_000.0
    )

    m = calculate_multipliers(report, banking_flow=50_000.0)

    assert m["ltm_fcf"] == 68_000.0
    assert m["ltm_core_fcf"] == 18_000.0
    assert m["fcf_basis"] == "core"


def test_bank_still_has_no_fcf(report_factory):
    """Разделение биржи и банка не должно вернуть банку FCF."""
    m = calculate_multipliers(
        report_factory(report_type="bank", operating_cash_flow=80_000.0, capex=12_000.0)
    )

    assert m["ltm_fcf"] is None
    assert m["debt_to_equity"] is None


def test_exchange_has_no_net_debt(report_factory):
    """Наличность биржи — деньги клиентов, чистым долгом её считать нельзя."""
    m = calculate_multipliers(
        report_factory(report_type="exchange", debt=0.0, cash_and_equivalents=691_623.0)
    )

    assert m["net_debt"] is None
    assert m["net_debt_to_fcf"] is None


# ─── Гудвил и материальная балансовая стоимость ────────────────────────────
#
# Грэм считал балансовую стоимость без гудвила: продать его отдельно нельзя,
# денег он не приносит, а при неудачной сделке списывается разом. Поэтому в
# таблице показывается P/B по материальному капиталу, а отчётный уходит в
# подсказку. База: капитализация 100 млрд, капитал 50 млрд, активы 100 млрд.


def test_no_goodwill_leaves_tangible_fields_empty(report):
    """Без гудвила материального P/B не существует — он совпал бы с обычным."""
    m = calculate_multipliers(report)

    assert m["pb_ratio"] == 2.0
    assert m["goodwill"] is None
    assert m["pb_tangible"] is None
    assert m["goodwill_to_assets"] is None


def test_goodwill_raises_pb_and_reports_share(report_factory):
    """Гудвил уменьшает капитал, поэтому материальный P/B всегда выше отчётного."""
    m = calculate_multipliers(report_factory(goodwill=10_000.0))

    assert m["pb_ratio"] == 2.0                    # 100 000 / 50 000
    assert m["tangible_equity"] == 40_000.0        # 50 000 − 10 000
    assert m["pb_tangible"] == 2.5                 # 100 000 / 40 000
    assert m["goodwill_to_assets"] == 10.0         # 10 000 / 100 000


def test_goodwill_share_counted_from_assets_not_equity(report_factory):
    """Доля считается от активов: порог значка в интерфейсе привязан к ним."""
    m = calculate_multipliers(report_factory(goodwill=25_000.0))

    assert m["goodwill_to_assets"] == 25.0         # 25 000 / 100 000, не 50%
    assert m["pb_tangible"] == 4.0                 # 100 000 / 25 000


def test_goodwill_equal_to_equity_gives_no_tangible_pb(report_factory):
    """Материальный капитал ушёл в ноль — делить не на что, но доля видна."""
    m = calculate_multipliers(report_factory(goodwill=50_000.0))

    assert m["tangible_equity"] == 0.0
    assert m["pb_tangible"] is None
    assert m["goodwill_to_assets"] == 50.0
    assert m["pb_ratio"] == 2.0                    # отчётный не пострадал


def test_goodwill_above_equity_gives_negative_tangible_equity(report_factory):
    """Гудвил больше капитала: по материальным активам компания в минусе."""
    m = calculate_multipliers(report_factory(goodwill=60_000.0))

    assert m["tangible_equity"] == -10_000.0
    assert m["pb_tangible"] is None


def test_goodwill_without_assets_still_gives_tangible_pb(report_factory):
    """Доля неизвестна без активов, но сам материальный P/B считается."""
    m = calculate_multipliers(report_factory(goodwill=10_000.0, total_assets=None))

    assert m["pb_tangible"] == 2.5
    assert m["goodwill_to_assets"] is None


def test_goodwill_ignored_without_equity(report_factory):
    """Нет капитала — нет и материального: вычитать не из чего."""
    m = calculate_multipliers(report_factory(goodwill=10_000.0, equity=None))

    assert m["pb_ratio"] is None
    assert m["pb_tangible"] is None
    assert m["tangible_equity"] is None
    assert m["goodwill_to_assets"] == 10.0
