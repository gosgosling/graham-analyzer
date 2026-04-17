"""
Enum-типы для моделей приложения.
"""
from enum import Enum


class PeriodType(str, Enum):
    """Тип отчётного периода"""
    QUARTERLY = "quarterly"
    ANNUAL = "annual"
    SEMI_ANNUAL = "semi_annual"


class AccountingStandard(str, Enum):
    """Стандарт бухгалтерской отчётности"""
    IFRS = "IFRS"  # Международные стандарты финансовой отчётности (МСФО)
    RAS = "RAS"    # Российские стандарты бухгалтерского учёта (РСБУ)
    US_GAAP = "US_GAAP"  # Общепринятые принципы бухгалтерского учёта США
    UK_GAAP = "UK_GAAP"  # Британские стандарты
    OTHER = "OTHER"  # Другие стандарты


class ReportSource(str, Enum):
    """Источник данных отчёта"""
    MANUAL = "manual"  # Введён вручную
    COMPANY_WEBSITE = "company_website"  # С сайта компании
    API = "api"  # Получен через API
    REGULATOR = "regulator"  # С сайта регулятора (ЦБ, SEC)
    OTHER = "other"  # Другой источник


class ReportType(str, Enum):
    """Тип компании/отрасли — определяет набор полей и алгоритм анализа по Грэму"""
    GENERAL = "general"  # Промышленные, нефтегаз, ритейл и т.д.
    BANK = "bank"        # Банки и финансовые учреждения


# Ключевые слова секторов T-Invest API, которые идентифицируют банки/финансовые институты.
# T-Invest API возвращает sector как строку (например, "financials", "banks", "financial").
_BANK_SECTOR_KEYWORDS = frozenset({
    "banks",
    "bank",
    "banking",
    "financials",
    "financial",
    "financial_services",
    "финансы",
    "банки",
    "банк",
})


def sector_to_report_type(sector: str | None) -> str:
    """
    Определяет report_type компании по её сектору из T-Invest API.

    Возвращает 'bank' если сектор относится к банковскому/финансовому сектору,
    иначе 'general'.

    Args:
        sector: строка сектора из поля Company.sector (может быть None)

    Returns:
        'bank' или 'general'
    """
    if not sector:
        return ReportType.GENERAL.value
    normalized = sector.strip().lower()
    if normalized in _BANK_SECTOR_KEYWORDS:
        return ReportType.BANK.value
    # Частичное совпадение: "financial_services", "bank_of_russia" и т.п.
    for keyword in _BANK_SECTOR_KEYWORDS:
        if keyword in normalized:
            return ReportType.BANK.value
    return ReportType.GENERAL.value
