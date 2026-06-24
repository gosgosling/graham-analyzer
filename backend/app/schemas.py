from pydantic import BaseModel, model_validator, computed_field, field_serializer
from typing import Optional, List, Union
from datetime import date, datetime
from app.models.enums import PeriodType, AccountingStandard, ReportSource
from app.services.analysis.share_counts import compute_circulation_shares

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
    brand_logo_url: Optional[str] = None  # URL логотипа (CDN Т-Банка)
    brand_color: Optional[str] = None  # Основной цвет бренда (#RRGGBB)
    # Тикер представляет привилегированные акции (см. модель Company)
    is_preferred_share: bool = False

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
    brand_logo_url: Optional[str] = None
    brand_color: Optional[str] = None
    # Тикер представляет привилегированные акции. При синхронизации из
    # T-Invest автодетектится по суффиксу «P»; вручную правится через PATCH.
    is_preferred_share: Optional[bool] = None


class FinancialReportCreate(BaseModel):
    """
    Схема для создания финансового отчёта.

    ⚠️ ЕДИНИЦЫ ВВОДА:
      - price_per_share, price_at_filing, dividends_per_share — в полных ₽ или $ (за акцию)
      - shares_* — количество акций в штуках:
          shares_issued — размещённое (общее), обязательно
          shares_outstanding — в обращении (опционально; иначе issued − treasury)
          shares_weighted_avg — средневзвешенное (опционально)
          treasury_shares — казначейские (опционально)
      - revenue, net_income, net_income_reported, total_assets, current_assets,
        total_liabilities, current_liabilities, equity — в МИЛЛИОНАХ валюты (млн ₽ или млн $)

    Пример: выручка Сбербанка 1 459 000 млн ₽ → вводить 1459000
    """
    company_id: int

    # Атрибуты отчёта
    period_type: PeriodType = PeriodType.QUARTERLY
    fiscal_year: int
    fiscal_quarter: Optional[int] = None
    accounting_standard: AccountingStandard = AccountingStandard.IFRS
    consolidated: bool = True
    source: ReportSource = ReportSource.MANUAL

    # Даты
    report_date: str   # YYYY-MM-DD
    filing_date: Optional[str] = None

    # Рыночные данные (полные единицы — ₽/$  за акцию)
    price_per_share: Optional[float] = None
    price_at_filing: Optional[float] = None
    shares_issued: Optional[int] = None
    shares_outstanding: Optional[int] = None
    shares_weighted_avg: Optional[int] = None
    treasury_shares: Optional[int] = None

    # Финансовые показатели — в МИЛЛИОНАХ валюты (млн ₽ или млн $)
    revenue: Optional[float] = None
    net_income: Optional[float] = None
    net_income_reported: Optional[float] = None  # фактическая отчётная прибыль, млн
    total_assets: Optional[float] = None
    current_assets: Optional[float] = None
    total_liabilities: Optional[float] = None
    current_liabilities: Optional[float] = None
    equity: Optional[float] = None
    cash_and_equivalents: Optional[float] = None  # наличность, млн
    debt: Optional[float] = None                  # долг, млн
    dividends_per_share: Optional[float] = None  # ₽/$ за акцию (полные единицы)
    dividends_paid: bool = False
    has_preferred_shares: bool = False
    preferred_share_dividends: Optional[float] = None  # млн валюты отчёта

    # ─── Банковские показатели (заполняются только для банков) ───
    # revenue при этом = Total Operating Income (NII + комиссии + трейдинг + прочее)
    # current_assets / current_liabilities оставляем None — для банков неприменимо
    net_interest_income: Optional[float] = None      # Чистые процентные доходы, млн
    fee_commission_income: Optional[float] = None    # Чистые комиссионные доходы, млн
    operating_expenses: Optional[float] = None       # Операционные расходы (до резервов), млн
    provisions: Optional[float] = None               # Резервы под обесценение, млн

    # ─── Денежные потоки (ОДДС) ───────────────────────────────────────────────
    # Для банков FCF концептуально неприменим, поля оставляем None.
    # capex — положительное число (абсолютная величина оттока), млн валюты.
    operating_cash_flow: Optional[float] = None  # Операционный денежный поток, млн
    capex: Optional[float] = None                # CAPEX (положит. число), млн
    lease_principal: Optional[float] = None      # Тело аренды, млн (положит. отток)
    lease_interest: Optional[float] = None       # Проценты по аренде, млн
    debt_principal: Optional[float] = None       # Тело долга (долг. ЦБ), млн
    # Амортизация и износ (D&A), млн — для сопоставления с CAPEX; не в формулах мультипликаторов.
    depreciation_amortization: Optional[float] = None

    # Валюта
    currency: str = "RUB"
    exchange_rate: Optional[float] = None

    # ─── AI-извлечение и верификация ───
    # При создании вручную: auto_extracted=False, verified_by_analyst=True (значения по умолчанию).
    # При создании AI-парсером: auto_extracted=True, verified_by_analyst=False + extraction_* поля.
    auto_extracted: bool = False
    verified_by_analyst: bool = True
    extraction_notes: Optional[str] = None
    extraction_model: Optional[str] = None
    source_pdf_path: Optional[str] = None

    @model_validator(mode='after')
    def validate_report(self):
        """Валидация полей отчёта"""
        # Проверка курса валюты для любой иностранной валюты (не только USD).
        # Если курс не задан — конвертация в рубли невозможна, а мультипликаторы
        # (P/E, P/B) для сравнения с MOEX-ценой будут некорректными.
        if self.currency and self.currency.upper() != "RUB" and not self.exchange_rate:
            raise ValueError(
                f"Курс {self.currency}/RUB обязателен для отчётов в {self.currency}. "
                f"Укажите его вручную или используйте автозагрузку с MOEX/ЦБ РФ."
            )
        
        # Проверка квартала для квартальных отчётов
        if self.period_type == PeriodType.QUARTERLY:
            if self.fiscal_quarter is None:
                raise ValueError("Для квартальных отчётов необходимо указать fiscal_quarter (1-4)")
            if not (1 <= self.fiscal_quarter <= 4):
                raise ValueError("fiscal_quarter должен быть от 1 до 4")
        
        # Для годовых отчётов квартал должен быть None
        if self.period_type == PeriodType.ANNUAL and self.fiscal_quarter is not None:
            raise ValueError("Для годовых отчётов fiscal_quarter должен быть None")

        if self.shares_issued is None and self.shares_outstanding is None and self.shares_weighted_avg is None:
            raise ValueError(
                "Укажите размещённое (общее) количество акций (shares_issued). "
                "Остальные поля акций — опциональны."
            )

        if (
            self.shares_issued is not None
            and self.treasury_shares is not None
            and self.treasury_shares > self.shares_issued
        ):
            raise ValueError("Казначейские акции не могут превышать размещённое количество")

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
    
    # Даты — принимают date/datetime от ORM, сериализуются в строки для JSON
    report_date: Union[date, str]
    filing_date: Optional[Union[date, str]] = None

    # Рыночные данные
    price_per_share: Optional[float] = None
    price_at_filing: Optional[float] = None
    shares_issued: Optional[int] = None
    shares_outstanding: Optional[int] = None
    shares_weighted_avg: Optional[int] = None
    treasury_shares: Optional[int] = None

    # Финансовые показатели
    revenue: Optional[float] = None
    net_income: Optional[float] = None
    net_income_reported: Optional[float] = None
    total_assets: Optional[float] = None
    current_assets: Optional[float] = None
    total_liabilities: Optional[float] = None
    current_liabilities: Optional[float] = None
    equity: Optional[float] = None
    cash_and_equivalents: Optional[float] = None  # наличность, млн
    debt: Optional[float] = None                  # долг, млн
    dividends_per_share: Optional[float] = None
    dividends_paid: bool = False
    has_preferred_shares: bool = False
    preferred_share_dividends: Optional[float] = None

    # Тип отрасли
    report_type: str = "general"

    # Банковские показатели
    net_interest_income: Optional[float] = None
    fee_commission_income: Optional[float] = None
    operating_expenses: Optional[float] = None
    provisions: Optional[float] = None

    # Денежные потоки (ОДДС)
    operating_cash_flow: Optional[float] = None  # Операционный поток, млн
    capex: Optional[float] = None                # CAPEX (положит. число), млн
    lease_principal: Optional[float] = None
    lease_interest: Optional[float] = None
    debt_principal: Optional[float] = None
    depreciation_amortization: Optional[float] = None  # D&A, млн

    # Валюта
    currency: str = "RUB"
    exchange_rate: Optional[float] = None

    # ─── AI-извлечение и верификация ───
    auto_extracted: bool = False
    verified_by_analyst: bool = True
    extraction_notes: Optional[str] = None
    extraction_model: Optional[str] = None
    source_pdf_path: Optional[str] = None
    verified_at: Optional[Union[datetime, str]] = None

    # Метаданные
    created_at: Optional[Union[datetime, str]] = None
    updated_at: Optional[Union[datetime, str]] = None

    class Config:
        from_attributes = True

    # Сериализаторы — конвертируют date/datetime в ISO-строку при отдаче JSON
    @field_serializer('report_date', 'filing_date')
    def serialize_date(self, v: Optional[Union[date, str]]) -> Optional[str]:
        if v is None:
            return None
        if isinstance(v, (date, datetime)):
            return v.isoformat()
        return str(v)

    @field_serializer('created_at', 'updated_at', 'verified_at')
    def serialize_datetime(self, v: Optional[Union[datetime, str]]) -> Optional[str]:
        if v is None:
            return None
        if isinstance(v, datetime):
            return v.isoformat()
        return str(v)

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
        """Цена акции (на дату окончания периода) в рублях"""
        return self._convert_to_rub(self.price_per_share)

    @computed_field  # type: ignore
    @property
    def price_at_filing_rub(self) -> Optional[float]:
        """Цена акции (на дату публикации) в рублях"""
        return self._convert_to_rub(self.price_at_filing)

    @computed_field  # type: ignore
    @property
    def shares_outstanding_effective(self) -> Optional[int]:
        """Акции в обращении: явное значение или размещённые − казначейские."""
        return compute_circulation_shares(
            self.shares_outstanding,
            self.shares_issued,
            self.treasury_shares,
        )

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
    def net_income_reported_rub(self) -> Optional[float]:
        """Фактическая отчётная прибыль в рублях"""
        return self._convert_to_rub(self.net_income_reported)

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
    def cash_and_equivalents_rub(self) -> Optional[float]:
        """Денежные средства и эквиваленты в рублях, млн"""
        return self._convert_to_rub(self.cash_and_equivalents)

    @computed_field  # type: ignore
    @property
    def debt_rub(self) -> Optional[float]:
        """Долг в рублях, млн"""
        return self._convert_to_rub(self.debt)

    @computed_field  # type: ignore
    @property
    def net_debt(self) -> Optional[float]:
        """Чистый долг = Долг − Наличность, млн валюты отчёта."""
        from app.services.analysis.net_debt import compute_net_debt

        return compute_net_debt(self.debt, self.cash_and_equivalents)

    @computed_field  # type: ignore
    @property
    def net_debt_rub(self) -> Optional[float]:
        """Чистый долг в рублях, млн"""
        return self._convert_to_rub(self.net_debt)

    @computed_field  # type: ignore
    @property
    def dividends_per_share_rub(self) -> Optional[float]:
        """Дивиденды на акцию в рублях"""
        return self._convert_to_rub(self.dividends_per_share)

    @computed_field  # type: ignore
    @property
    def fcf(self) -> Optional[float]:
        """FCF = OCF − CAPEX − аренда (тело, %) − тело долга; млн валюты отчёта."""
        from app.services.analysis.fcf import compute_fcf

        return compute_fcf(
            self.operating_cash_flow,
            self.capex,
            self.lease_principal,
            self.lease_interest,
            self.debt_principal,
        )

    @computed_field  # type: ignore
    @property
    def operating_cash_flow_rub(self) -> Optional[float]:
        """Операционный денежный поток в рублях, млн"""
        return self._convert_to_rub(self.operating_cash_flow)

    @computed_field  # type: ignore
    @property
    def capex_rub(self) -> Optional[float]:
        """CAPEX в рублях, млн"""
        return self._convert_to_rub(self.capex)

    @computed_field  # type: ignore
    @property
    def depreciation_amortization_rub(self) -> Optional[float]:
        """Амортизация и износ в рублях, млн"""
        return self._convert_to_rub(self.depreciation_amortization)

    @computed_field  # type: ignore
    @property
    def fcf_rub(self) -> Optional[float]:
        """FCF в рублях, млн"""
        return self._convert_to_rub(self.fcf)

    @computed_field  # type: ignore
    @property
    def adjusted_net_income(self) -> Optional[float]:
        """Чистая прибыль для обыкновенных акций: NI − дивиденды по префам (млн валюты)."""
        if self.net_income is None:
            return None
        sub = float(self.preferred_share_dividends or 0) if self.has_preferred_shares else 0.0
        return round(self.net_income - sub, 3)

    @computed_field  # type: ignore
    @property
    def adjusted_fcf(self) -> Optional[float]:
        """FCF для обыкновенных: OCF − CAPEX − дивиденды по префам (млн валюты)."""
        base = self.fcf
        if base is None:
            return None
        sub = float(self.preferred_share_dividends or 0) if self.has_preferred_shares else 0.0
        return round(base - sub, 3)

    @computed_field  # type: ignore
    @property
    def adjusted_net_income_rub(self) -> Optional[float]:
        return self._convert_to_rub(self.adjusted_net_income)

    @computed_field  # type: ignore
    @property
    def adjusted_fcf_rub(self) -> Optional[float]:
        return self._convert_to_rub(self.adjusted_fcf)


# ---------------------------------------------------------------------------
# StockPrice schemas
# ---------------------------------------------------------------------------

class StockPriceResponse(BaseModel):
    """Схема ответа для записи исторической цены акции."""
    id: int
    company_id: int
    date: date
    price: float
    source: str
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Multiplier schemas
# ---------------------------------------------------------------------------

class MultiplierResponse(BaseModel):
    """Схема ответа для кэшированных мультипликаторов."""
    id: int
    company_id: int
    report_id: Optional[int] = None
    date: date
    type: str

    # Рыночные данные
    price_used: Optional[float] = None
    shares_used: Optional[int] = None
    shares_issued: Optional[int] = None
    shares_outstanding_circulation: Optional[int] = None
    shares_cap_explanation: Optional[str] = None
    market_cap: Optional[float] = None

    # LTM P&L
    ltm_net_income: Optional[float] = None
    ltm_revenue: Optional[float] = None
    ltm_dividends_per_share: Optional[float] = None

    # Балансовые данные
    equity: Optional[float] = None
    total_liabilities: Optional[float] = None
    current_assets: Optional[float] = None
    current_liabilities: Optional[float] = None

    # Мультипликаторы
    pe_ratio: Optional[float] = None
    pb_ratio: Optional[float] = None
    roe: Optional[float] = None
    debt_to_equity: Optional[float] = None
    current_ratio: Optional[float] = None
    dividend_yield: Optional[float] = None
    cost_to_income: Optional[float] = None  # % — только для банков

    # Денежные потоки LTM (NULL для банков)
    ltm_fcf: Optional[float] = None
    ltm_operating_cash_flow: Optional[float] = None
    # Мультипликаторы FCF (NULL для банков)
    price_to_fcf: Optional[float] = None
    fcf_to_net_income: Optional[float] = None  # %, детектор качества прибыли

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    # Из связанного отчёта: дата публикации и цена на эту дату (в ₽), для подсказки в UI
    filing_date: Optional[date] = None
    price_at_filing_rub: Optional[float] = None

    class Config:
        from_attributes = True


class CurrentMultipliersResponse(BaseModel):
    """Схема ответа для «живых» актуальных мультипликаторов (вычисляются на лету)."""
    company_id: int
    date: str
    current_price: Optional[float] = None
    balance_report_id: Optional[int] = None
    balance_report_date: Optional[str] = None
    ltm_source: Optional[str] = None

    # LTM P&L
    ltm_net_income: Optional[float] = None
    ltm_revenue: Optional[float] = None
    ltm_dividends_per_share: Optional[float] = None

    # Расчётные данные
    price_used: Optional[float] = None
    shares_used: Optional[int] = None
    shares_issued: Optional[int] = None
    shares_outstanding_circulation: Optional[int] = None
    shares_cap_explanation: Optional[str] = None
    market_cap: Optional[float] = None
    equity: Optional[float] = None  # собственный капитал, млн ₽ (из балансового отчёта)

    # Мультипликаторы
    pe_ratio: Optional[float] = None
    pb_ratio: Optional[float] = None
    roe: Optional[float] = None
    debt_to_equity: Optional[float] = None
    current_ratio: Optional[float] = None
    dividend_yield: Optional[float] = None
    cost_to_income: Optional[float] = None  # % — только для банков

    # Денежные потоки LTM (NULL для банков)
    ltm_fcf: Optional[float] = None
    ltm_operating_cash_flow: Optional[float] = None
    # Мультипликаторы FCF (NULL для банков)
    price_to_fcf: Optional[float] = None
    fcf_to_net_income: Optional[float] = None  # %, детектор качества прибыли


class PriceUpdateResponse(BaseModel):
    """Ответ при обновлении цены компании."""
    company_id: int
    ticker: str
    figi: str
    price: Optional[float]
    updated_at: Optional[datetime] = None
    success: bool


# ---------------------------------------------------------------------------
# Company with current price
# ---------------------------------------------------------------------------

class CompanyWithPrice(BaseModel):
    """Расширенная схема компании с текущей ценой."""
    id: int
    figi: str
    ticker: str
    name: str
    isin: Optional[str] = None
    sector: Optional[str] = None
    currency: str
    lot: int
    current_price: Optional[float] = None
    price_updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class DividendContinuityResult(BaseModel):
    """Результат анализа непрерывности выплаты дивидендов"""
    company_id: int
    dividend_start_year: Optional[int] = None
    years_of_continuous_payments: int  # Количество лет непрерывных выплат
    is_continuous: bool  # Выплачиваются ли дивиденды непрерывно
    last_payment_year: Optional[int] = None
    gap_years: List[int] = []  # Годы, когда дивиденды не выплачивались
    recommendation: str  # Рекомендация на основе непрерывности


class PostgresBackupResponse(BaseModel):
    """Результат POST /admin/backup/postgres"""
    status: str = "ok"
    filename: str
    path: str
    size_bytes: int
    size_human: str
    message: str
    