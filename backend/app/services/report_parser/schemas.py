"""Схемы результата извлечения из PDF.

Эта схема одновременно служит:
  * JSON-схемой для структурированного вывода LLM (response_format=json_object),
  * валидатором ответа модели,
  * промежуточным DTO между парсером и слоем записи в БД.

Поля сознательно сделаны Optional — LLM должен вернуть null, если значение
в отчёте не найдено, а не выдумывать.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


# Маппинг подписей, которые LLM иногда возвращает из PDF (вместо ISO-кода),
# в канонический код валюты. Например: подпись таблицы "в млн руб." модель
# иногда цепляет в currency как "руб." — из-за чего потом Pydantic в
# FinancialReportCreate требует exchange_rate для "не-RUB" валюты и падает.
_CURRENCY_ALIASES = {
    # Русский
    "руб": "RUB", "руб.": "RUB", "рубли": "RUB", "рубль": "RUB", "рублей": "RUB",
    "ру́б.": "RUB", "₽": "RUB",
    # Английский
    "rub": "RUB", "rur": "RUB", "rubles": "RUB", "ruble": "RUB",
    "usd": "USD", "us$": "USD", "$": "USD", "dollar": "USD", "dollars": "USD",
    "eur": "EUR", "euro": "EUR", "€": "EUR",
    "cny": "CNY", "rmb": "CNY", "yuan": "CNY", "¥": "CNY",
    "gbp": "GBP", "£": "GBP",
    "jpy": "JPY",
    "chf": "CHF",
}


def _normalize_currency(raw: Optional[str]) -> str:
    """Приводит валюту, возвращённую LLM из PDF, к ISO-4217 коду.

    Без этой нормализации бывают случаи: LLM находит в шапке таблицы подпись
    вроде «в млн руб.» и кладёт в currency строку «руб.». Далее Pydantic-
    валидатор `FinancialReportCreate` воспринимает «руб.» ≠ «RUB» и требует
    exchange_rate — отчёт зависает на ошибке. Нормализуем один раз на входе.
    """
    if not raw:
        return "RUB"
    key = str(raw).strip().lower().rstrip(".").strip()
    if not key:
        return "RUB"
    # Сначала смотрим в alias-таблицу (там покрыты "руб", "usd", "€" и т.п.).
    if key in _CURRENCY_ALIASES:
        return _CURRENCY_ALIASES[key]
    # Затем — ASCII ISO-4217 (USD, EUR, CNY). Важно именно ASCII, чтобы "руб"
    # (3 кириллических) не провалился как ISO-код "РУБ".
    if len(key) == 3 and key.isalpha() and key.isascii():
        return key.upper()
    return str(raw).upper()


ReportTypeLiteral = Literal["general", "bank"]
PeriodTypeLiteral = Literal["annual", "quarterly", "semi_annual"]
AccountingStandardLiteral = Literal["IFRS", "RAS", "US_GAAP", "UK_GAAP", "OTHER"]


class ExtractedReport(BaseModel):
    """Структурированный результат извлечения из одного PDF."""

    # ─── Идентификация периода ───────────────────────────────────────────────
    # fiscal_year и report_date — Optional: ожидаемый год всё равно известен из
    # формы загрузки и принудительно проставляется в extractor_service. Делаем
    # их необязательными, чтобы ответ модели не падал на валидации, если она их
    # не вернула (json_object не гарантирует наличие всех полей).
    fiscal_year: Optional[int] = Field(
        None, description="Отчётный год, например 2023"
    )
    period_type: PeriodTypeLiteral = Field(
        "annual", description="annual для годовых, quarterly для квартальных"
    )
    fiscal_quarter: Optional[int] = Field(
        None, ge=1, le=4, description="Номер квартала 1..4 (только для quarterly)"
    )
    accounting_standard: AccountingStandardLiteral = Field(
        "IFRS", description="Стандарт отчётности: МСФО → IFRS, РСБУ → RAS"
    )
    consolidated: bool = Field(True, description="Консолидированная ли отчётность")
    report_date: Optional[str] = Field(
        None,
        description="Дата окончания отчётного периода в формате YYYY-MM-DD "
                    "(обычно 31.12.{fiscal_year})",
    )
    filing_date: Optional[str] = Field(
        None, description="Дата публикации отчёта YYYY-MM-DD, если указана"
    )

    report_type: ReportTypeLiteral = Field(
        "general",
        description="general — промышленные/нефтегаз/ритейл; bank — банки и фин. институты",
    )

    # ─── Валюта и единицы ────────────────────────────────────────────────────
    currency: str = Field("RUB", description="Валюта отчёта: RUB / USD / EUR ...")

    @field_validator("currency", mode="before")
    @classmethod
    def _normalize_currency_code(cls, v):
        return _normalize_currency(v)
    units_scale: Literal["units", "thousands", "millions", "billions"] = Field(
        "millions",
        description=(
            "В каких единицах даны ЧИСЛА В ОТЧЁТЕ (не в ответе!). "
            "Если в шапке 'в миллионах' — millions; 'в тыс.' — thousands; "
            "голые рубли — units; 'в млрд' — billions. "
            "Используется для конвертации в итоговые миллионы."
        ),
    )

    # ─── Балансовые показатели (в ИСХОДНЫХ единицах отчёта!) ─────────────────
    # После получения от LLM мы сами приведём их в миллионы согласно units_scale.
    total_assets: Optional[float] = Field(
        None,
        description=(
            "Итого активы. Синонимы в отчётах: 'Итого активов', 'Всего активов', "
            "'Активы — всего', 'Total assets', 'Баланс' (в конце раздела активы)."
        ),
    )
    total_liabilities: Optional[float] = Field(
        None,
        description=(
            "Итого обязательства (ВСЕ, долгосрочные + краткосрочные). "
            "Синонимы в отчётах: 'Итого обязательств', 'Всего обязательств', "
            "'Обязательства — всего', 'Total liabilities'. "
            "Может располагаться ПЕРЕД строкой 'Итого капитал и обязательства' / "
            "'Баланс'. Если прямой строки нет — сложи все подитоги обязательств "
            "(долгосрочные + краткосрочные) и укажи это в extraction_notes."
        ),
    )
    current_assets: Optional[float] = Field(
        None,
        description=(
            "Итого оборотные активы. СИНОНИМЫ (в российских МСФО встречаются все): "
            "'Оборотные активы', 'Текущие активы', 'Краткосрочные активы', "
            "'Итого оборотных активов', 'Итого краткосрочных активов', "
            "'Current assets', 'Total current assets'. "
            "НЕ заполнять для банков — оставить null."
        ),
    )
    current_liabilities: Optional[float] = Field(
        None,
        description=(
            "Итого краткосрочные обязательства. СИНОНИМЫ: "
            "'Краткосрочные обязательства', 'Текущие обязательства', "
            "'Итого краткосрочных обязательств', 'Итого текущих обязательств', "
            "'Current liabilities', 'Total current liabilities'. "
            "НЕ заполнять для банков — оставить null."
        ),
    )
    equity: Optional[float] = Field(
        None,
        description="Итого капитал (акционеров материнской компании), в ИСХОДНЫХ единицах",
    )
    cash_and_equivalents: Optional[float] = Field(
        None,
        description=(
            "Денежные средства и их эквиваленты на конец периода — строка из "
            "АКТИВОВ баланса (раздел оборотных активов). СИНОНИМЫ: 'Денежные "
            "средства и их эквиваленты', 'Денежные средства и краткосрочные "
            "депозиты', 'Cash and cash equivalents'. Бери значение на конец "
            "отчётного периода. НЕ путай с 'денежными средствами с ограничением "
            "к использованию' (restricted cash) — их не включай. В ИСХОДНЫХ единицах."
        ),
    )
    debt: Optional[float] = Field(
        None,
        description=(
            "Суммарный процентный ДОЛГ (только кредиты и займы!) = краткосрочные "
            "кредиты и займы + долгосрочные кредиты и займы. СИНОНИМЫ строк: "
            "'Кредиты и займы', 'Краткосрочные кредиты и займы', 'Долгосрочные "
            "кредиты и займы', 'Заёмные средства', 'Облигации', 'Borrowings', "
            "'Loans and borrowings'. "
            "ВКЛЮЧАЙ обязательства по аренде (лизингу), если они стоят в строке "
            "кредитов; иначе аренду НЕ добавляй. "
            "НЕ включай: торговую/прочую кредиторскую задолженность, налоги, "
            "резервы, отложенные налоговые обязательства, авансы — это НЕ долг. "
            "Сложи краткосрочную и долгосрочную части и укажи разбивку в "
            "extraction_notes. В ИСХОДНЫХ единицах отчёта."
        ),
    )

    # ─── Отчёт о движении денежных средств (ОДДС / Cash Flow Statement) ──────
    operating_cash_flow: Optional[float] = Field(
        None,
        description=(
            "Чистый денежный поток от ОПЕРАЦИОННОЙ деятельности (OCF) за отчётный "
            "год. СИНОНИМЫ: 'Чистые денежные средства от операционной "
            "деятельности', 'Денежные потоки от операционной деятельности — "
            "итого', 'Net cash from operating activities', 'Net cash generated "
            "by operating activities'. Бери ИТОГОВУЮ строку раздела операционной "
            "деятельности. Может быть отрицательным. В ИСХОДНЫХ единицах."
        ),
    )
    capex: Optional[float] = Field(
        None,
        description=(
            "Капитальные затраты (CAPEX) из раздела ИНВЕСТИЦИОННОЙ деятельности "
            "ОДДС. СИНОНИМЫ: 'Приобретение основных средств', 'Приобретение "
            "основных средств и нематериальных активов', 'Покупка основных "
            "средств', 'Purchase of property, plant and equipment', 'Capital "
            "expenditures'. Если приобретение ОС и НМА указаны раздельно — сложи "
            "их. Записывай ПОЛОЖИТЕЛЬНЫМ числом (абсолютная величина оттока), "
            "даже если в отчёте оно в скобках/со знаком минус. В ИСХОДНЫХ единицах."
        ),
    )
    lease_principal: Optional[float] = Field(
        None,
        description=(
            "Погашение ТЕЛА обязательств по аренде (лизингу) из раздела "
            "ФИНАНСОВОЙ деятельности ОДДС. СИНОНИМЫ: 'Погашение обязательств по "
            "аренде', 'Выплаты основной суммы обязательств по аренде', "
            "'Payment of lease liabilities', 'Principal elements of lease "
            "payments'. ПОЛОЖИТЕЛЬНОЕ число (величина оттока). Если проценты по "
            "аренде включены в эту же строку — раздели по возможности и отметь в "
            "extraction_notes. В ИСХОДНЫХ единицах."
        ),
    )
    lease_interest: Optional[float] = Field(
        None,
        description=(
            "ПРОЦЕНТЫ, уплаченные по обязательствам аренды (лизинга). СИНОНИМЫ: "
            "'Проценты по аренде уплаченные', 'Процентная составляющая платежей "
            "по аренде', 'Interest on lease liabilities', 'Interest portion of "
            "lease payments'. Часто указаны в разделе финансовой/операционной "
            "деятельности ОДДС либо в примечании про аренду. ПОЛОЖИТЕЛЬНОЕ число. "
            "Если отдельно не выделены — оставь null и отметь это в "
            "extraction_notes. В ИСХОДНЫХ единицах."
        ),
    )

    # ─── Отчёт о прибылях и убытках ──────────────────────────────────────────
    revenue: Optional[float] = Field(
        None,
        description=(
            "Выручка за период. Для банков — Total Operating Income "
            "(NII + комиссии + трейдинг + прочие операц. доходы)."
        ),
    )
    net_income: Optional[float] = Field(
        None,
        description=(
            "Чистая прибыль акционеров материнской компании (нормализованная). "
            "Если в отчёте несколько строк (до/после учёта меньшинства), бери "
            "«Прибыль, относящаяся к акционерам ПАО ...»."
        ),
    )
    net_income_reported: Optional[float] = Field(
        None,
        description=(
            "Фактическая отчётная прибыль — та, что указана в строке 'Чистая прибыль' "
            "без каких-либо нормализаций. Может совпадать с net_income."
        ),
    )

    # ─── Дивиденды ──────────────────────────────────────────────────────────
    dividends_per_share: Optional[float] = Field(
        None,
        description=(
            "Дивиденды на одну обыкновенную акцию в ПОЛНЫХ единицах валюты (₽/$). "
            "Брать итоговые начисленные за отчётный год. Null если не указано."
        ),
    )
    dividends_paid: bool = Field(
        False, description="Выплачивались ли дивиденды в отчётном периоде"
    )

    # ─── Акции ──────────────────────────────────────────────────────────────
    shares_outstanding: Optional[int] = Field(
        None,
        description=(
            "Количество обыкновенных акций — ПРЕДПОЧТИТЕЛЬНО 'Средневзвешенное "
            "количество обыкновенных акций' (weighted average) из раздела про EPS. "
            "Если средневзвешенного нет — бери на конец периода. "
            "ВАЖНО: пиши ЧИСЛО КАК В ОТЧЁТЕ, без самостоятельного умножения на 1000. "
            "Единицы (штуки/тысячи) укажи в shares_units_scale."
        ),
    )
    shares_units_scale: Literal["units", "thousands", "millions"] = Field(
        "units",
        description=(
            "В каких единицах записано shares_outstanding. Определяй по ПОДПИСИ "
            "рядом со строкой или в шапке таблицы: "
            "'Средневзвешенное количество обыкновенных акций (ТЫС. ШТУК)' → thousands; "
            "'Средневзвешенное количество обыкновенных акций (МЛН. ШТУК)' → millions "
            "(встречается у Татнефти, Лукойла и др. — число обычно 2-3 значное, "
            "реальное количество измеряется миллиардами); "
            "'В обращении 692 865 762 акции' / 'штук' → units. "
            "Если не уверен — thousands (чаще встречается в российских МСФО)."
        ),
    )

    # ─── Банковские поля (только при report_type='bank') ────────────────────
    net_interest_income: Optional[float] = Field(
        None, description="Чистые процентные доходы (NII), банки"
    )
    fee_commission_income: Optional[float] = Field(
        None, description="Чистые комиссионные доходы, банки"
    )
    operating_expenses: Optional[float] = Field(
        None, description="Операционные расходы до резервов, банки"
    )
    provisions: Optional[float] = Field(
        None, description="Резервы под обесценение кредитов (со знаком расхода), банки"
    )

    # ─── Заметки модели ─────────────────────────────────────────────────────
    extraction_notes: Optional[str] = Field(
        None,
        description=(
            "Короткие пометки (1-5 строк) о сделанных допущениях: какие строки "
            "не нашлись, как был нормализован net_income, откуда взята валюта, "
            "в каких единицах был отчёт и т.п. ОБЯЗАТЕЛЬНО помечай неуверенные "
            "значения."
        ),
    )

    @field_validator("extraction_notes", mode="before")
    @classmethod
    def _coerce_notes_to_string(cls, v):
        """Модель в json_object-режиме иногда отдаёт extraction_notes списком
        строк (по пунктам). Склеиваем в единый текст, чтобы пройти валидацию."""
        if v is None or isinstance(v, str):
            return v
        if isinstance(v, (list, tuple)):
            return "\n".join(str(item).strip() for item in v if str(item).strip())
        return str(v)

    confidence: Optional[Literal["low", "medium", "high"]] = Field(
        None, description="Общая уверенность модели в извлечённых данных"
    )


# ─── Конвертация единиц в итоговые миллионы ─────────────────────────────────

_SCALE_TO_MILLIONS: dict[str, float] = {
    "units": 1 / 1_000_000,
    "thousands": 1 / 1_000,
    "millions": 1.0,
    "billions": 1_000.0,
}

# Поля, которые хранятся в БД в МИЛЛИОНАХ и поэтому подлежат пересчёту.
_MONETARY_FIELDS_IN_MILLIONS: tuple[str, ...] = (
    "total_assets",
    "total_liabilities",
    "current_assets",
    "current_liabilities",
    "equity",
    "cash_and_equivalents",
    "debt",
    "revenue",
    "net_income",
    "net_income_reported",
    "net_interest_income",
    "fee_commission_income",
    "operating_expenses",
    "provisions",
    # ОДДС
    "operating_cash_flow",
    "capex",
    "lease_principal",
    "lease_interest",
)


_SHARES_SCALE_TO_UNITS: dict[str, int] = {
    "units": 1,
    "thousands": 1_000,
    "millions": 1_000_000,
}


def rescale_to_millions(report: ExtractedReport) -> ExtractedReport:
    """
    Привести извлечённые данные к каноническому виду:
      * монетарные поля — в миллионы валюты (согласно `units_scale`);
      * shares_outstanding — в штуки (согласно `shares_units_scale`).

    После вызова:
      * `units_scale == "millions"`,
      * `shares_units_scale == "units"`,
    а соответствующие значения уже пересчитаны.

    Поля, которые всегда в полных единицах валюты (dividends_per_share),
    НЕ трогаем.
    """
    money_factor = _SCALE_TO_MILLIONS.get(report.units_scale, 1.0)
    shares_factor = _SHARES_SCALE_TO_UNITS.get(report.shares_units_scale, 1)

    if money_factor == 1.0 and shares_factor == 1:
        return report

    data = report.model_dump()

    if money_factor != 1.0:
        for field in _MONETARY_FIELDS_IN_MILLIONS:
            value = data.get(field)
            if value is not None:
                data[field] = float(value) * money_factor
        data["units_scale"] = "millions"

    if shares_factor != 1 and data.get("shares_outstanding") is not None:
        data["shares_outstanding"] = int(data["shares_outstanding"]) * shares_factor
        data["shares_units_scale"] = "units"

    return ExtractedReport.model_validate(data)
