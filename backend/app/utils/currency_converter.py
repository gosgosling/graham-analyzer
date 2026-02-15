from typing import Optional, Dict
from app.models.financial_report import FinancialReport

def convert_to_rub(value: Optional[float], currency: str, exchange_rate: Optional[float]) -> Optional[float]:
    """
    Конвертирует значение в рубли.
    
    Args:
        value: Значение для конвертации (может быть None)
        currency: Валюта исходного значения
        exchange_rate: Курс обмена (USD/RUB)
        
    Returns:
        Значение в рублях или None если value is None
    """
    if value is None:
        return None
    if currency == "USD" and exchange_rate:
        return value * exchange_rate
    return value


def get_report_values_in_rub(report: FinancialReport) -> Dict[str, Optional[float]]:
    """
    Возвращает все финансовые показатели отчета сконвертированными в рубли.
    
    Args:
        report: Объект финансового отчета
        
    Returns:
        Словарь с показателями в рублях
    """
    def convert(value: Optional[float]) -> Optional[float]:
        if value is None:
            return None
        return convert_to_rub(float(value), report.currency, 
                             float(report.exchange_rate) if report.exchange_rate else None)
    
    return {
        "price_per_share_rub": convert(report.price_per_share),
        "revenue_rub": convert(report.revenue),
        "net_income_rub": convert(report.net_income),
        "total_assets_rub": convert(report.total_assets),
        "current_assets_rub": convert(report.current_assets),
        "total_liabilities_rub": convert(report.total_liabilities),
        "current_liabilities_rub": convert(report.current_liabilities),
        "equity_rub": convert(report.equity),
        "dividends_per_share_rub": convert(report.dividends_per_share),
    }


def get_report_with_rub_values(report: FinancialReport) -> Dict:
    """
    Возвращает отчет с дополнительными полями в рублях для удобства использования.
    
    Args:
        report: Объект финансового отчета
        
    Returns:
        Словарь с оригинальными и сконвертированными значениями
    """
    rub_values = get_report_values_in_rub(report)
    
    return {
        "id": report.id,
        "company_id": report.company_id,
        "report_date": report.report_date.isoformat(),
        "currency": report.currency,
        "exchange_rate": float(report.exchange_rate) if report.exchange_rate else None,
        
        # Оригинальные значения
        "price_per_share": float(report.price_per_share) if report.price_per_share else None,
        "shares_outstanding": report.shares_outstanding,
        "revenue": float(report.revenue) if report.revenue else None,
        "net_income": float(report.net_income) if report.net_income else None,
        "total_assets": float(report.total_assets) if report.total_assets else None,
        "current_assets": float(report.current_assets) if report.current_assets else None,
        "total_liabilities": float(report.total_liabilities) if report.total_liabilities else None,
        "current_liabilities": float(report.current_liabilities) if report.current_liabilities else None,
        "equity": float(report.equity) if report.equity else None,
        "dividends_per_share": float(report.dividends_per_share) if report.dividends_per_share else None,
        "dividends_paid": report.dividends_paid,
        
        # Значения в рублях
        **rub_values,
        
        "created_at": report.created_at.isoformat() if report.created_at else None,
        "updated_at": report.updated_at.isoformat() if report.updated_at else None,
    }
