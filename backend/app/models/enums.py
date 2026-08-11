"""
Enum-типы для моделей приложения.
"""
from enum import Enum
from typing import Optional


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


class CompanyType(str, Enum):
    """Метод анализа компании — не отрасль.

    Отрасль (`Company.sector`) отвечает на вопрос «с кем сравнивать», тип —
    «как считать». Их смешение стоило дорого: АФК Система и SFI имеют сектор
    `financial`, из-за чего получали банковские метрики и норматив
    достаточности капитала, которого у холдинга не существует.
    """

    INDUSTRIAL = "industrial"  # обычный бизнес: весь набор тестов Грэма
    LENDER = "lender"          # банки, МФО, лизинг, ломбарды: активы — займы
    INSURANCE = "insurance"    # страховщики: резервы и комбинированный коэффициент
    HOLDING = "holding"        # владеет долями, сам не оперирует: NAV, а не P/E
    HYBRID = "hybrid"          # операционка со встроенным финбизнесом (Яндекс)
    # Биржа, клиринг, депозитарий. Баланс раздут чужими деньгами и зеркальными
    # позициями центрального контрагента: у МОЕХ активы и обязательства ЦК
    # совпадают до рубля (10,2 трлн с обеих сторон), а свой капитал — 0,27 трлн.
    # Отсюда D/E 47× — не риск, а способ учёта. Кредитного портфеля нет,
    # поэтому и банковские метрики риска неприменимы.
    EXCHANGE = "exchange"      # инфраструктура рынка: биржа, клиринг, депозитарий


class ReportType(str, Enum):
    """Тип компании/отрасли — определяет набор полей и алгоритм анализа по Грэму"""
    GENERAL = "general"    # Промышленные, нефтегаз, ритейл и т.д.
    BANK = "bank"          # Банки и финансовые учреждения
    EXCHANGE = "exchange"  # Биржа и клиринг: без плеча и кредитных метрик, но с FCF


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


def company_type_to_report_type(company_type: Optional[str]) -> str:
    """Набор полей отчёта по типу компании.

    Банковский набор (портфель, резервы, Н1) нужен только кредиторам.
    Гибрид (Яндекс с банком внутри) остаётся в общем наборе: его финсегмент
    оценивается отдельно, а не подменяет отчётность всей компании.
    Биржа — третий случай: плечо и ликвидность у неё считать нельзя, как у
    банка, но кредитных метрик нет, а свободный поток осмыслен.
    """
    ct = (company_type or "").strip().lower()
    if ct == CompanyType.LENDER.value:
        return ReportType.BANK.value
    if ct == CompanyType.EXCHANGE.value:
        return ReportType.EXCHANGE.value
    return ReportType.GENERAL.value


def sector_to_company_type(sector: str | None) -> str:
    """Первичная догадка о типе по сектору — только для новых компаний.

    Сектор `financial` объединяет банки, страховщиков, биржи и холдинги,
    поэтому догадка всегда требует ручной проверки: по умолчанию ставим
    `industrial`, чтобы новая компания молча не получила чужие метрики.
    """
    return CompanyType.INDUSTRIAL.value
