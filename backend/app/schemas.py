from pydantic import BaseModel, model_validator, computed_field
from typing import Optional, List
from app.models.enums import PeriodType, AccountingStandard, ReportSource

class Security(BaseModel):
    secid: str
    boardid: str
    shortname: str
    prevprice: Optional[float] = None
    lotsize: int
    facevalue: float
    status: str
    boardname: str
    decimals: int
    secname: str
    remarks: Optional[str] = None
    marketcode: str
    instrid: str
    sectorid: Optional[str] = None
    minstep: float
    prevwaprice: Optional[float] = None
    faceunit: str
    prevdate: Optional[str] = None  # Будет строка из API
    issuesize: int
    isin: str
    latname: str
    regnumber: Optional[str] = None
    prevlegalcloseprice: Optional[float] = None
    currencyid: str
    sectype: str
    listlevel: int
    settledate: Optional[str] = None  # Будет строка из API 

class Multipliers(BaseModel):
    company_id: int
    pe_ratio: float
    pb_ratio: float
    debt_to_equity: float
    roe: float
    dividend_yield: float
    date: str

class AnalysisItem(BaseModel):
    security: Security
    multipliers: Multipliers
    category: str

class AnalysisResponse(BaseModel):
    undervalued: list[AnalysisItem]
    stable: list[AnalysisItem]
    overvalued: list[AnalysisItem]

class CompanyResult(BaseModel):
    company_id: int
    company_name: str
    category: str
    multipliers: Multipliers
    analysis: dict
    recommendation: str
    date: str


class AnalysisDetails(BaseModel):
    pe_ratio_status: str
    pb_ratio_status: str
    debt_status: str
    liquidity_status: str
    profitability_status: str

class Company(BaseModel):
    """Схема для компании из Tinkoff Invest API"""
    id: Optional[int] = None  # ID из базы данных (может отсутствовать при создании)
    figi: str  # FIGI - уникальный идентификатор инструмента
    ticker: str  # Тикер
    name: str  # Название компании
    isin: str # ISIN для связи с MOEX
    sector: Optional[str] = None  # Сектор
    currency: str  # Валюта
    lot: int  # Размер лота
    api_trade_available_flag: bool = False  # Доступность для торговли через API

    class Config:
        from_attributes = True  # Для SQLAlchemy моделей


class CompanyCreate(BaseModel):
    figi: str
    ticker: str
    name: str
    isin: str
    sector: Optional[str] = None
    currency: str = "RUB"
    lot: int = 1
    api_trade_available_flag: bool = False
    dividend_start_year: Optional[int] = None  # Год начала выплаты дивидендов


class FinancialReportCreate(BaseModel):
    """Схема для создания финансового отчета"""
    company_id: int
    
    # Атрибуты отчёта
    period_type: PeriodType = PeriodType.QUARTERLY
    fiscal_year: int
    fiscal_quarter: Optional[int] = None  # NULL для годовых отчётов
    accounting_standard: AccountingStandard = AccountingStandard.IFRS
    consolidated: bool = True
    source: ReportSource = ReportSource.MANUAL
    
    # Даты
    report_date: str  # YYYY-MM-DD формат (дата окончания отчётного периода)
    filing_date: Optional[str] = None  # YYYY-MM-DD формат (дата публикации)
    
    # Рыночные данные
    price_per_share: Optional[float] = None
    shares_outstanding: Optional[int] = None
    
    # Финансовые показатели
    revenue: Optional[float] = None
    net_income: Optional[float] = None
    total_assets: Optional[float] = None
    current_assets: Optional[float] = None
    total_liabilities: Optional[float] = None
    current_liabilities: Optional[float] = None
    equity: Optional[float] = None
    dividends_per_share: Optional[float] = None
    dividends_paid: bool = False
    
    # Валюта
    currency: str = "RUB"
    exchange_rate: Optional[float] = None

    @model_validator(mode='after')
    def validate_report(self):
        """Валидация полей отчёта"""
        # Проверка курса валюты
        if self.currency == "USD" and not self.exchange_rate:
            raise ValueError("Курс доллара обязателен для USD отчетов")
        
        # Проверка квартала для квартальных отчётов
        if self.period_type == PeriodType.QUARTERLY:
            if self.fiscal_quarter is None:
                raise ValueError("Для квартальных отчётов необходимо указать fiscal_quarter (1-4)")
            if not (1 <= self.fiscal_quarter <= 4):
                raise ValueError("fiscal_quarter должен быть от 1 до 4")
        
        # Для годовых отчётов квартал должен быть None
        if self.period_type == PeriodType.ANNUAL and self.fiscal_quarter is not None:
            raise ValueError("Для годовых отчётов fiscal_quarter должен быть None")
        
        return self


class FinancialReport(BaseModel):
    """Схема для ответа API с финансовым отчетом"""
    id: int
    company_id: int
    
    # Атрибуты отчёта
    period_type: str
    fiscal_year: int
    fiscal_quarter: Optional[int] = None
    accounting_standard: str
    consolidated: bool
    source: str
    
    # Даты
    report_date: str  # YYYY-MM-DD формат
    filing_date: Optional[str] = None
    
    # Рыночные данные
    price_per_share: Optional[float] = None
    shares_outstanding: Optional[int] = None
    
    # Финансовые показатели
    revenue: Optional[float] = None
    net_income: Optional[float] = None
    total_assets: Optional[float] = None
    current_assets: Optional[float] = None
    total_liabilities: Optional[float] = None
    current_liabilities: Optional[float] = None
    equity: Optional[float] = None
    dividends_per_share: Optional[float] = None
    dividends_paid: bool = False
    
    # Валюта
    currency: str = "RUB"
    exchange_rate: Optional[float] = None
    
    # Метаданные
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    class Config:
        from_attributes = True

    # Вспомогательный метод конвертации
    def _convert_to_rub(self, value: Optional[float]) -> Optional[float]:
        """Конвертирует значение в рубли с учетом валюты и курса"""
        if value is None:
            return None
        if self.currency == "USD" and self.exchange_rate:
            return round(value * self.exchange_rate, 2)
        return value

    # Computed fields - автоматически добавляются к ответу API
    @computed_field  # type: ignore
    @property
    def price_per_share_rub(self) -> Optional[float]:
        """Цена акции в рублях"""
        return self._convert_to_rub(self.price_per_share)

    @computed_field  # type: ignore
    @property
    def revenue_rub(self) -> Optional[float]:
        """Выручка в рублях"""
        return self._convert_to_rub(self.revenue)

    @computed_field  # type: ignore
    @property
    def net_income_rub(self) -> Optional[float]:
        """Чистая прибыль в рублях"""
        return self._convert_to_rub(self.net_income)

    @computed_field  # type: ignore
    @property
    def total_assets_rub(self) -> Optional[float]:
        """Общие активы в рублях"""
        return self._convert_to_rub(self.total_assets)

    @computed_field  # type: ignore
    @property
    def current_assets_rub(self) -> Optional[float]:
        """Текущие активы в рублях"""
        return self._convert_to_rub(self.current_assets)

    @computed_field  # type: ignore
    @property
    def total_liabilities_rub(self) -> Optional[float]:
        """Общие обязательства в рублях"""
        return self._convert_to_rub(self.total_liabilities)

    @computed_field  # type: ignore
    @property
    def current_liabilities_rub(self) -> Optional[float]:
        """Текущие обязательства в рублях"""
        return self._convert_to_rub(self.current_liabilities)

    @computed_field  # type: ignore
    @property
    def equity_rub(self) -> Optional[float]:
        """Собственный капитал в рублях"""
        return self._convert_to_rub(self.equity)

    @computed_field  # type: ignore
    @property
    def dividends_per_share_rub(self) -> Optional[float]:
        """Дивиденды на акцию в рублях"""
        return self._convert_to_rub(self.dividends_per_share)


class DividendContinuityResult(BaseModel):
    """Результат анализа непрерывности выплаты дивидендов"""
    company_id: int
    dividend_start_year: Optional[int] = None
    years_of_continuous_payments: int  # Количество лет непрерывных выплат
    is_continuous: bool  # Выплачиваются ли дивиденды непрерывно
    last_payment_year: Optional[int] = None
    gap_years: List[int] = []  # Годы, когда дивиденды не выплачивались
    recommendation: str  # Рекомендация на основе непрерывности
    