from app.models.financial_report import FinancialReport


from app.utils.currency_converter import convert_to_rub

def calculate_multipliers(report: FinancialReport):
    # Конвертируем все значения в рубли перед расчетом
    revenue_rub = convert_to_rub(report.revenue, report.currency, report.exchange_rate)
    net_income_rub = convert_to_rub(report.net_income, report.currency, report.exchange_rate)
    # ... и т.д.
