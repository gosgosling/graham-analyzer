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
