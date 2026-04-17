from app.models.financial_report import FinancialReport
from app.utils.currency_converter import convert_to_rub
from typing import Dict, Optional

# ⚠️ Финансовые показатели (P&L и баланс) хранятся в МИЛЛИОНАХ валюты.
# Цена акции и дивиденды на акцию — в полных единицах (₽ или $ за акцию).
# Количество акций — в штуках.
#
# Для расчёта P/E и P/B необходимо привести показатели к одним единицам:
#   market_cap = price_per_share × shares_outstanding  → полные рубли
#   net_income, equity и т.д. → млн ₽ × MILLION = полные рубли
#
# ROE, D/E, Current Ratio — безразмерные отношения, миллионы сокращаются.
# Dividend Yield — оба значения в полных рублях на акцию.

MILLION = 1_000_000


def calculate_multipliers(
    report: FinancialReport,
    override_price: Optional[float] = None,
    override_shares: Optional[int] = None,
    ltm_net_income: Optional[float] = None,
    ltm_revenue: Optional[float] = None,
    ltm_dividends_per_share: Optional[float] = None,
) -> Dict[str, Optional[float]]:
    """
    Рассчитывает финансовые мультипликаторы.

    Поведение зависит от report.report_type:
    - "general": стандартный набор (P/E, P/B, ROE, D/E, Current Ratio, Dividend Yield)
    - "bank": банковский набор (P/E, P/B, ROE, Dividend Yield, Cost-to-Income)
              D/E и Current Ratio не рассчитываются — для банков не применимы.

    Args:
        report: Финансовый отчёт (источник балансовых данных и валюты)
        override_price: Переопределить цену акции (в полных ₽/$ за акцию)
        override_shares: Переопределить количество акций
        ltm_net_income: LTM чистая прибыль в млн валюты отчёта (None → из отчёта)
        ltm_revenue: LTM выручка / Total Operating Income в млн (None → из отчёта)
        ltm_dividends_per_share: LTM дивиденды на акцию в ₽/$ (None → из отчёта)

    Returns:
        Словарь с мультипликаторами. market_cap — в МИЛЛИОНАХ рублей.
    """
    is_bank = getattr(report, 'report_type', 'general') == 'bank'

    rate = float(report.exchange_rate) if report.exchange_rate else None
    currency = report.currency

    def to_rub_full(value) -> Optional[float]:
        """Конвертировать полное значение (цена на акцию) в рубли."""
        return convert_to_rub(float(value) if value is not None else None, currency, rate)

    def to_rub_mln(value) -> Optional[float]:
        """Конвертировать значение в млн валюты → млн рублей."""
        return convert_to_rub(float(value) if value is not None else None, currency, rate)

    # Цена и количество акций (полные единицы)
    price_raw = override_price if override_price is not None else report.price_per_share
    price_rub = to_rub_full(price_raw)
    shares = override_shares if override_shares is not None else report.shares_outstanding

    # P&L (в млн валюты → млн рублей)
    net_income_mln = (
        to_rub_mln(ltm_net_income) if ltm_net_income is not None
        else to_rub_mln(report.net_income)
    )
    dividends_per_share_rub = (
        to_rub_full(ltm_dividends_per_share) if ltm_dividends_per_share is not None
        else to_rub_full(report.dividends_per_share)
    )

    # Балансовые (в млн валюты → млн рублей)
    equity_mln = to_rub_mln(report.equity)
    total_liabilities_mln = to_rub_mln(report.total_liabilities)
    current_assets_mln = to_rub_mln(report.current_assets)
    current_liabilities_mln = to_rub_mln(report.current_liabilities)

    # Рыночная капитализация в полных рублях, затем переводим в млн для хранения
    market_cap_full: Optional[float] = None
    market_cap_mln: Optional[float] = None
    if price_rub and shares:
        market_cap_full = price_rub * shares
        market_cap_mln = round(market_cap_full / MILLION, 3)

    # P/E = Market Cap (полн. руб.) / Net Income (полн. руб.)
    pe_ratio: Optional[float] = None
    if market_cap_full and net_income_mln and net_income_mln > 0:
        pe_ratio = round(market_cap_full / (net_income_mln * MILLION), 2)

    # P/B = Market Cap (полн.) / Equity (полн.)
    pb_ratio: Optional[float] = None
    if market_cap_full and equity_mln and equity_mln > 0:
        pb_ratio = round(market_cap_full / (equity_mln * MILLION), 2)

    # ROE = Net Income / Equity × 100%  (миллионы сокращаются)
    roe: Optional[float] = None
    if net_income_mln is not None and equity_mln and equity_mln != 0:
        roe = round(net_income_mln / equity_mln * 100, 2)

    # Dividend Yield = Dividends per Share / Price × 100%  (оба в полных рублях)
    dividend_yield: Optional[float] = None
    if dividends_per_share_rub and price_rub and price_rub > 0:
        dividend_yield = round(dividends_per_share_rub / price_rub * 100, 2)

    # ─── Показатели, зависящие от типа отрасли ───────────────────────────────
    debt_to_equity: Optional[float] = None
    current_ratio: Optional[float] = None
    cost_to_income: Optional[float] = None

    if is_bank:
        # Для банков D/E и Current Ratio не применяются:
        # депозиты — обязательства по природе, D/E 8-10x — норма.
        # Вместо них рассчитываем Cost-to-Income (CIR).
        #
        # CIR = Operating Expenses / Total Operating Income × 100%
        # revenue хранит Total Operating Income для банков
        revenue_for_cir = (
            to_rub_mln(ltm_revenue) if ltm_revenue is not None
            else to_rub_mln(report.revenue)
        )
        opex_mln = to_rub_mln(report.operating_expenses)
        if opex_mln and revenue_for_cir and revenue_for_cir > 0:
            cost_to_income = round(opex_mln / revenue_for_cir * 100, 2)
    else:
        # Стандартные показатели для промышленных компаний
        if total_liabilities_mln and equity_mln and equity_mln != 0:
            debt_to_equity = round(total_liabilities_mln / equity_mln, 2)

        if current_assets_mln and current_liabilities_mln and current_liabilities_mln != 0:
            current_ratio = round(current_assets_mln / current_liabilities_mln, 2)

    return {
        "pe_ratio": pe_ratio,
        "pb_ratio": pb_ratio,
        "roe": roe,
        "debt_to_equity": debt_to_equity,
        "current_ratio": current_ratio,
        "dividend_yield": dividend_yield,
        "cost_to_income": cost_to_income,
        "market_cap": market_cap_mln,          # млн рублей
        "price_used": round(price_rub, 4) if price_rub else None,  # ₽ за акцию
        "shares_used": shares,
    }
