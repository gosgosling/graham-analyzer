"""Схемы финансового отчёта — самая большая часть контракта API.

Инварианты (единицы, валюта отчёта, приоритет акций) описаны в docstring
самих схем: они же служат документацией на /docs.
"""
from datetime import date, datetime
from functools import lru_cache
from typing import Dict, Optional, Union

from pydantic import BaseModel, computed_field, field_serializer, model_validator

from app.models.enums import AccountingStandard, PeriodType, ReportSource
from app.services.analysis.bank_metrics import (
    bank_metric_hint,
    compute_bank_metrics,
    evaluate_all,
)
from app.services.analysis.fcf import compute_banking_flow, compute_core_fcf, compute_fcf
from app.services.analysis.interest_coverage import compute_interest_coverage
from app.services.analysis.payout import compute_dividend_payout
from app.services.analysis.share_counts import compute_circulation_shares


@lru_cache(maxsize=64)
def _key_rate_for(year: int) -> Optional[float]:
    """Средняя ключевая ставка ЦБ за год из справочника.

    Кэшируется: справочник меняется раз в год, а схема строится на каждый
    отчёт в списке. Отсутствие года — не ошибка: спред просто не считается.
    """
    from app.database import SessionLocal
    from app.models.key_rate import KeyRate

    db = SessionLocal()
    try:
        row = db.query(KeyRate).filter(KeyRate.year == year).first()
        return float(row.avg_rate) if row else None
    finally:
        db.close()


# Показатели, знаменатель которых — весь баланс или весь отчёт о прибыли.
# Для банка это и есть финансовый бизнес, для гибрида — вся компания.
_CREDIT_METRICS = (
    "cost_of_risk",
    "npl_ratio",
    "npl_basis",
    "npl_coverage",
    "loans_to_deposits",
    "retail_loans_share",
    "retail_deposits_share",
    "gross_loans",
    "net_loans",
)

_EXCHANGE_METRICS = ("fee_share", "opex_to_fees", "client_funds", "client_funds_to_equity")

_GROUP_LEVEL_METRICS = (
    "roa",
    "net_interest_margin",
    "cost_of_funding",
    "funding_spread",
    "capital_adequacy_ratio",
    "capital_adequacy_core",
    "capital_to_rwa",
    "key_rate",
)


class BankMetricsOut(BaseModel):
    """Банковские показатели отчёта вместе со светофором.

    Пороги считает бэкенд, а не интерфейс: иначе одна и та же метрика
    покрасится по-разному в карточке и в таблице, как это уже случалось
    с отраслевыми порогами.
    """

    roa: Optional[float] = None
    net_interest_margin: Optional[float] = None
    cost_of_risk: Optional[float] = None
    npl_ratio: Optional[float] = None
    npl_basis: Optional[str] = None
    fee_share: Optional[float] = None
    opex_to_fees: Optional[float] = None
    client_funds: Optional[float] = None
    client_funds_to_equity: Optional[float] = None
    npl_coverage: Optional[float] = None
    loans_to_deposits: Optional[float] = None
    cost_of_funding: Optional[float] = None
    capital_adequacy_ratio: Optional[float] = None
    capital_adequacy_core: Optional[float] = None
    capital_to_rwa: Optional[float] = None
    retail_loans_share: Optional[float] = None
    retail_deposits_share: Optional[float] = None
    funding_spread: Optional[float] = None
    key_rate: Optional[float] = None
    gross_loans: Optional[float] = None
    net_loans: Optional[float] = None
    # Откуда потоки: 'ltm' | 'annualised' | 'reported' — интерфейс подписывает
    # период, чтобы удвоение полугодия не выдавалось за факт.
    flow_basis: Optional[str] = None
    # Чей это финансовый бизнес: 'lender' — вся компания, 'hybrid' — сегмент
    # внутри обычной. У гибрида часть показателей намеренно пустая.
    segment: Optional[str] = None
    # Свободный поток ядра — только у гибрида (млн ₽)
    reported_fcf: Optional[float] = None
    banking_flow: Optional[float] = None
    banking_flow_basis: Optional[str] = None
    core_fcf: Optional[float] = None

    statuses: Dict[str, str] = {}   # метрика → good | normal | bad | n/a
    hints: Dict[str, str] = {}      # метрика → пояснение к порогу


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
    # Прибыль до процентов и налогов и стоимость обслуживания долга:
    # их отношение — покрытие процентов.
    operating_profit: Optional[float] = None   # Операционная прибыль (EBIT), млн
    finance_costs: Optional[float] = None      # Финансовые расходы, млн (положительное число)

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
    provisions: Optional[float] = None               # Резерв ЗА ПЕРИОД, млн (положительное число)
    # Валовые процентные потоки — из них видна стоимость фондирования.
    interest_income: Optional[float] = None          # Процентные доходы (валовые), млн
    interest_expense: Optional[float] = None         # Процентные расходы, млн (положительное число)
    # Кредитный портфель: баланс показывает его за вычетом резерва, валовая
    # сумма и накопленный резерв — в примечании «Кредиты клиентам».
    gross_loans: Optional[float] = None              # Кредиты клиентам до вычета резерва, млн
    loan_loss_allowance: Optional[float] = None      # Накопленный резерв (ECL), млн
    npl_loans: Optional[float] = None                # Обесцененные кредиты (Стадия 3 + POCI), млн
    # Просрочка 90+ — механический признак неплатежа. Уже Стадии 3: та
    # включает реструктурированные кредиты, по которым платежи идут.
    npl_overdue_90: Optional[float] = None            # Ссуды с задержкой свыше 90 дней, млн
    customer_deposits: Optional[float] = None        # Средства клиентов, млн
    # Разбивка на розницу и корпоратив: розничные депозиты дешевле и устойчивее,
    # розничные кредиты доходнее и рискованнее.
    loans_retail: Optional[float] = None             # Кредиты физлицам (валовые), млн
    loans_corporate: Optional[float] = None          # Кредиты юрлицам (валовые), млн
    deposits_retail: Optional[float] = None          # Средства физлиц, млн
    deposits_corporate: Optional[float] = None       # Средства юрлиц, млн
    # Движение клиентских денег из ОДДС — для встроенного финсервиса.
    # Переписываются из отчёта СО ЗНАКОМ: приток депозитов положительный,
    # выдача кредитов отрицательная. Разница балансовых остатков для этого
    # не годится: она включает секьюритизацию и списания.
    cf_customer_deposits: Optional[float] = None   # Изменение средств клиентов (ОДДС), млн
    cf_customer_loans: Optional[float] = None      # Изменение кредитов клиентам (ОДДС), млн

    # Достаточность капитала — ограничитель роста и дивидендов банка.
    risk_weighted_assets: Optional[float] = None     # Активы, взвешенные по риску, млн
    capital_adequacy_ratio: Optional[float] = None   # Н1.0 общий / Total capital ratio, %
    capital_adequacy_core: Optional[float] = None    # Н1.1 / CET1 — основной капитал, %

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

    @computed_field  # type: ignore
    @property
    def dividend_payout(self) -> Optional[float]:
        """Доля прибыли, выплаченная дивидендами, %.

        Не банковский показатель: выплата сверх заработанного одинаково
        тревожна у банка и у металлурга. Для убытка не считается — payout от
        отрицательной прибыли выглядит как аккуратное число вместо
        предупреждения.
        """
        return compute_dividend_payout(self)

    @computed_field  # type: ignore
    @property
    def interest_coverage(self) -> Optional[float]:
        """Во сколько раз операционная прибыль покрывает проценты по долгу.

        Тест устойчивости у Грэма и главный показатель холдинга: своих
        операций у него нет, а долг корпоративного центра обслуживать надо.

        Для банка не считается: у него процентные расходы — себестоимость
        основной деятельности, а не обслуживание долга. Сбер за 2025 год
        получил бы покрытие 0,38 при прибыли 1,7 трлн ₽ — ложная тревога
        у самого прибыльного банка страны.
        """
        if (self.report_type or "general") == "bank":
            return None
        return compute_interest_coverage(self)

    # ─── Банковский блок ─────────────────────────────────────────────────────

    @computed_field  # type: ignore
    @property
    def bank_metrics(self) -> Optional[BankMetricsOut]:
        """Стоимость риска, качество портфеля, фондирование и капитал.

        Считается только для банковских отчётов: у промышленной компании нет
        ни кредитного портфеля, ни Н1.0, и пустой блок в карточке лишний.
        Отношения не зависят от валюты — числитель и знаменатель из одного
        отчёта, — поэтому конвертация в рубли здесь не нужна.
        """
        report_type = self.report_type or "general"
        is_bank = report_type == "bank"
        is_exchange = report_type == "exchange"
        # У гибрида тип отчёта общий, но финсегмент внутри есть — его выдаёт
        # заполненный кредитный портфель. Признак по данным, а не по типу
        # компании: схема отчёта о компании ничего не знает.
        has_segment = self.gross_loans is not None
        if not is_bank and not is_exchange and not has_segment:
            return None

        metrics = compute_bank_metrics(self, key_rate=_key_rate_for(self.fiscal_year))
        values = metrics.as_dict()
        statuses = evaluate_all(metrics)
        if is_exchange:
            # Биржа не выдаёт займы: показателей риска у неё нет.
            for name in _CREDIT_METRICS:
                values[name] = None
                statuses[name] = "n/a"
        else:
            # Комиссии и клиентские остатки описывают инфраструктурный бизнес;
            # у банка доход от кредитования, и те же отношения значат другое.
            for name in _EXCHANGE_METRICS:
                values[name] = None
                statuses[name] = "n/a"
        if not is_bank and not is_exchange:
            # Знаменатели этих показателей — активы и капитал всей компании,
            # вместе с основным бизнесом. К финсегменту они не относятся.
            for name in _GROUP_LEVEL_METRICS:
                values[name] = None
                statuses[name] = "n/a"
        hints = {
            name: hint
            for name in statuses
            if (hint := bank_metric_hint(name)) is not None
        }
        # Поток ядра по этому отчёту — чтобы динамику по годам можно было
        # показать рядом с показателями, а не только за скользящий год.
        # Считается теми же функциями, что и в сервисе: формула живёт в fcf.py.
        if is_bank:
            reported_fcf = banking_flow = core_fcf = None
        else:
            reported_fcf = compute_fcf(
                self.operating_cash_flow, self.capex, self.lease_principal
            )
            banking_flow, _basis = compute_banking_flow(self)
            core_fcf = compute_core_fcf(reported_fcf, banking_flow)

        return BankMetricsOut(
            **values,
            reported_fcf=reported_fcf,
            banking_flow=banking_flow,
            core_fcf=core_fcf,
            segment="lender" if is_bank else "exchange" if is_exchange else "hybrid",
            statuses=statuses,
            hints=hints,
        )

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
