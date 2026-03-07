from app.models.financial_report import FinancialReport
from app.utils.currency_converter import convert_to_rub
from typing import Dict, Optional


def calculate_multipliers(
    report: FinancialReport,
    override_price: Optional[float] = None,
    override_shares: Optional[int] = None,
    ltm_net_income: Optional[float] = None,
    ltm_revenue: Optional[float] = None,
    ltm_dividends_per_share: Optional[float] = None,
) -> Dict[str, Optional[float]]:
    """
    Рассчитывает финансовые мультипликаторы на основе отчёта.
    Все расчёты производятся в рублях.

    Args:
        report: Финансовый отчёт компании (источник балансовых данных)
        override_price: Переопределить цену акции (например, текущая рыночная цена)
        override_shares: Переопределить количество акций
        ltm_net_income: LTM чистая прибыль (если None — берётся из отчёта)
        ltm_revenue: LTM выручка (если None — берётся из отчёта)
        ltm_dividends_per_share: LTM дивиденды на акцию (если None — из отчёта)

    Returns:
        Словарь с рассчитанными мультипликаторами
    """
    rate = float(report.exchange_rate) if report.exchange_rate else None
    currency = report.currency

    def to_rub(value) -> Optional[float]:
        return convert_to_rub(float(value) if value is not None else None, currency, rate)

    # Цена и количество акций
    price_raw = override_price if override_price is not None else report.price_per_share
    price_rub = to_rub(price_raw)

    shares = override_shares if override_shares is not None else report.shares_outstanding

    # P&L: используем LTM если переданы, иначе из отчёта
    net_income_rub = to_rub(ltm_net_income) if ltm_net_income is not None else to_rub(report.net_income)
    dividends_per_share_rub = (
        to_rub(ltm_dividends_per_share)
        if ltm_dividends_per_share is not None
        else to_rub(report.dividends_per_share)
    )

    # Балансовые данные — всегда из отчёта (снимок на дату)
    equity_rub = to_rub(report.equity)
    total_liabilities_rub = to_rub(report.total_liabilities)
    current_assets_rub = to_rub(report.current_assets)
    current_liabilities_rub = to_rub(report.current_liabilities)

    # Рыночная капитализация
    market_cap: Optional[float] = None
    if price_rub and shares:
        market_cap = price_rub * shares

    # P/E = Рыночная капитализация / Чистая прибыль LTM
    pe_ratio: Optional[float] = None
    if market_cap and net_income_rub and net_income_rub > 0:
        pe_ratio = round(market_cap / net_income_rub, 2)

    # P/B = Рыночная капитализация / Собственный капитал
    pb_ratio: Optional[float] = None
    if market_cap and equity_rub and equity_rub > 0:
        pb_ratio = round(market_cap / equity_rub, 2)

    # ROE = Чистая прибыль / Собственный капитал × 100%
    roe: Optional[float] = None
    if net_income_rub is not None and equity_rub and equity_rub != 0:
        roe = round(net_income_rub / equity_rub * 100, 2)

    # Debt/Equity = Общие обязательства / Собственный капитал
    debt_to_equity: Optional[float] = None
    if total_liabilities_rub and equity_rub and equity_rub != 0:
        debt_to_equity = round(total_liabilities_rub / equity_rub, 2)

    # Current Ratio = Оборотные активы / Краткосрочные обязательства
    current_ratio: Optional[float] = None
    if current_assets_rub and current_liabilities_rub and current_liabilities_rub != 0:
        current_ratio = round(current_assets_rub / current_liabilities_rub, 2)

    # Dividend Yield = Дивиденды на акцию / Цена × 100%
    dividend_yield: Optional[float] = None
    if dividends_per_share_rub and price_rub and price_rub > 0:
        dividend_yield = round(dividends_per_share_rub / price_rub * 100, 2)

    return {
        "pe_ratio": pe_ratio,
        "pb_ratio": pb_ratio,
        "roe": roe,
        "debt_to_equity": debt_to_equity,
        "current_ratio": current_ratio,
        "dividend_yield": dividend_yield,
        "market_cap": round(market_cap, 2) if market_cap else None,
        "price_used": round(price_rub, 2) if price_rub else None,
        "shares_used": shares,
    }
