"""Схемы финансового отчёта — самая большая часть контракта API.

Инварианты (единицы, валюта отчёта, приоритет акций) описаны в docstring
самих схем: они же служат документацией на /docs.
"""
from datetime import date, datetime
from typing import Optional, Union

from pydantic import BaseModel, computed_field, field_serializer, model_validator

from app.models.enums import AccountingStandard, PeriodType, ReportSource
from app.services.analysis.share_counts import compute_circulation_shares


class ReportFigures(BaseModel):
    """Показатели отчёта — то, что одинаково на входе и на выходе API.

    Раньше эти сорок полей были выписаны дважды: в схеме создания и в схеме
    ответа. Списки успели разойтись (`report_type` есть только в ответе), а
    каждое новое поле требовалось внести в обе копии — и однажды бы не внесли.
    Различаются у схем только идентификаторы и типы дат: на входе строки от
    формы, на выходе `date`/`datetime` от ORM. Они и остались в наследниках.

    ⚠️ ЕДИНИЦЫ: денежные показатели — в МИЛЛИОНАХ валюты отчёта; цена и
    дивиденд на акцию — в полных единицах (₽/$ за акцию); акции — в штуках.
    """

    # Рыночные данные (полные единицы — ₽/$ за акцию)
    price_per_share: Optional[float] = None
    price_at_filing: Optional[float] = None
    shares_issued: Optional[int] = None            # размещённое (общее)
    shares_outstanding: Optional[int] = None       # в обращении (иначе issued − treasury)
    shares_weighted_avg: Optional[int] = None      # средневзвешенное для EPS
    treasury_shares: Optional[int] = None          # казначейские

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
    dividends_per_share: Optional[float] = None   # ₽/$ за акцию, ВСЕГО (полные единицы)
    dividends_paid: bool = False
    # Разовая часть выплаты (входит в dividends_per_share): спецдивиденд,
    # компенсация пропущенных лет, распределение от продажи актива
    special_dividends_per_share: Optional[float] = None
    special_dividends_note: Optional[str] = None
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
    interest_paid: Optional[float] = None        # Проценты уплаченные (financing), млн
    debt_principal: Optional[float] = None       # Тело долга (долг. ЦБ), млн — не в FCF
    # Амортизация и износ (D&A), млн — для сопоставления с CAPEX; не в формулах мультипликаторов.
    depreciation_amortization: Optional[float] = None

    # Валюта
    currency: str = "RUB"
    exchange_rate: Optional[float] = None

    # ─── AI-извлечение и верификация ───
    # Вручную: auto_extracted=False, verified_by_analyst=True (значения по умолчанию).
    # AI-парсером: auto_extracted=True, verified_by_analyst=False + extraction_* поля.
    auto_extracted: bool = False
    verified_by_analyst: bool = True
    extraction_notes: Optional[str] = None
    extraction_model: Optional[str] = None
    source_pdf_path: Optional[str] = None


class FinancialReportCreate(ReportFigures):
    """
    Схема для создания финансового отчёта.

    ⚠️ ЕДИНИЦЫ ВВОДА:
      - price_per_share, price_at_filing, dividends_per_share — в полных ₽ или $ (за акцию)
      - shares_* — количество акций в штуках (все опциональны при создании черновика):
          shares_issued — размещённое (общее)
          shares_outstanding — в обращении (иначе issued − treasury)
          shares_weighted_avg — средневзвешенное
          treasury_shares — казначейские
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

        if (
            self.shares_issued is not None
            and self.treasury_shares is not None
            and self.treasury_shares > self.shares_issued
        ):
            raise ValueError("Казначейские акции не могут превышать размещённое количество")

        return self


class FinancialReport(ReportFigures):
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


    # Тип отрасли
    report_type: str = "general"

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
        """FCF = OCF − CAPEX − аренда − проценты уплаченные (financing); млн."""
        from app.services.analysis.fcf import compute_fcf

        return compute_fcf(
            self.operating_cash_flow,
            self.capex,
            self.lease_principal,
            self.lease_interest,
            self.interest_paid,
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
