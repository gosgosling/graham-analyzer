from app.models.financial_report import FinancialReport
from app.utils.currency_converter import convert_to_rub
from typing import Dict, Optional


def calculate_multipliers(report: FinancialReport) -> Dict[str, Optional[float]]:
    """
    Рассчитывает финансовые мультипликаторы на основе отчета.
    Все расчеты производятся в рублях (значения конвертируются автоматически).
    
    Args:
        report: Финансовый отчет компании
        
    Returns:
        Словарь с рассчитанными мультипликаторами
    """
    # Конвертируем все значения в рубли перед расчетом
    # convert_to_rub теперь принимает Optional[float]
    price_per_share_rub = convert_to_rub(
        float(report.price_per_share) if report.price_per_share else None,
        report.currency,
        float(report.exchange_rate) if report.exchange_rate else None
    )
    revenue_rub = convert_to_rub(
        float(report.revenue) if report.revenue else None,
        report.currency,
        float(report.exchange_rate) if report.exchange_rate else None
    )
    net_income_rub = convert_to_rub(
        float(report.net_income) if report.net_income else None,
        report.currency,
        float(report.exchange_rate) if report.exchange_rate else None
    )
    total_assets_rub = convert_to_rub(
        float(report.total_assets) if report.total_assets else None,
        report.currency,
        float(report.exchange_rate) if report.exchange_rate else None
    )
    current_assets_rub = convert_to_rub(
        float(report.current_assets) if report.current_assets else None,
        report.currency,
        float(report.exchange_rate) if report.exchange_rate else None
    )
    total_liabilities_rub = convert_to_rub(
        float(report.total_liabilities) if report.total_liabilities else None,
        report.currency,
        float(report.exchange_rate) if report.exchange_rate else None
    )
    current_liabilities_rub = convert_to_rub(
        float(report.current_liabilities) if report.current_liabilities else None,
        report.currency,
        float(report.exchange_rate) if report.exchange_rate else None
    )
    equity_rub = convert_to_rub(
        float(report.equity) if report.equity else None,
        report.currency,
        float(report.exchange_rate) if report.exchange_rate else None
    )
    dividends_per_share_rub = convert_to_rub(
        float(report.dividends_per_share) if report.dividends_per_share else None,
        report.currency,
        float(report.exchange_rate) if report.exchange_rate else None
    )
    
    # Рассчитываем мультипликаторы
    multipliers = {}
    
    # P/E = Цена акции / EPS (прибыль на акцию)
    if price_per_share_rub and net_income_rub and report.shares_outstanding and report.shares_outstanding > 0:
        eps = net_income_rub / report.shares_outstanding
        if eps > 0:
            multipliers['pe_ratio'] = round(price_per_share_rub / eps, 2)
        else:
            multipliers['pe_ratio'] = None
    else:
        multipliers['pe_ratio'] = None
    
    # P/B = Цена акции / Балансовая стоимость на акцию
    if price_per_share_rub and equity_rub and report.shares_outstanding and report.shares_outstanding > 0:
        book_value_per_share = equity_rub / report.shares_outstanding
        if book_value_per_share > 0:
            multipliers['pb_ratio'] = round(price_per_share_rub / book_value_per_share, 2)
        else:
            multipliers['pb_ratio'] = None
    else:
        multipliers['pb_ratio'] = None
    
    # Debt/Equity = Долг / Капитал
    if total_liabilities_rub and equity_rub and equity_rub > 0:
        multipliers['debt_to_equity'] = round(total_liabilities_rub / equity_rub, 2)
    else:
        multipliers['debt_to_equity'] = None
    
    # Current Ratio = Текущие активы / Текущие обязательства
    if current_assets_rub and current_liabilities_rub and current_liabilities_rub > 0:
        multipliers['current_ratio'] = round(current_assets_rub / current_liabilities_rub, 2)
    else:
        multipliers['current_ratio'] = None
    
    # ROE = (Чистая прибыль / Собственный капитал) * 100%
    if net_income_rub and equity_rub and equity_rub > 0:
        multipliers['roe'] = round((net_income_rub / equity_rub) * 100, 2)
    else:
        multipliers['roe'] = None
    
    # Dividend Yield = (Дивиденды на акцию / Цена акции) * 100%
    if dividends_per_share_rub and price_per_share_rub and price_per_share_rub > 0:
        multipliers['dividend_yield'] = round((dividends_per_share_rub / price_per_share_rub) * 100, 2)
    else:
        multipliers['dividend_yield'] = None
    
    return multipliers
