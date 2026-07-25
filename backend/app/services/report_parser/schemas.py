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

from app.utils.date_parse import normalize_date_str


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
        description=(
            "Дата окончания периода YYYY-MM-DD. Для годового отчёта всегда "
            "31.12.{fiscal_year}; можно null — сервер подставит сам."
        ),
    )
    filing_date: Optional[str] = Field(
        None,
        description=(
            "Дата публикации YYYY-MM-DD — обычно в конце аудиторского "
            "заключения перед балансом. Необязательна; null если не видна."
        ),
    )

    @field_validator("report_date", "filing_date", mode="before")
    @classmethod
    def _normalize_dates(cls, v):
        """LLM часто пишет «30.04.2021» — приводим к ISO до записи в БД."""
        if v is None or v == "":
            return None
        try:
            return normalize_date_str(v)
        except ValueError:
            # Пусть дальше упадёт с понятной ошибкой на сохранении, не на схеме LLM
            return v

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
            "CAPEX = сумма оттоков 'Приобретение основных средств' + "
            "'Приобретение нематериальных активов' из ИНВЕСТИЦИОННОЙ "
            "деятельности ОДДС (отдельного поля НМА нет — всегда складывай). "
            "Если одна строка 'ОС и НМА' — бери её. ПОЛОЖИТЕЛЬНОЕ число "
            "(модуль оттока). В extraction_notes: 'capex = ОС X + НМА Y'. "
            "В ИСХОДНЫХ единицах."
        ),
    )
    lease_principal: Optional[float] = Field(
        None,
        description=(
            "Арендные выплаты из ФИНАНСОВОЙ деятельности ОДДС. Если в отчёте "
            "одна строка 'Выплаты обязательств по аренде' / 'Погашение "
            "обязательств по аренде' / 'Payment of lease liabilities' без "
            "разделения на тело и проценты — положи ВСЮ сумму сюда, а "
            "lease_interest оставь null (НЕ оценивай проценты). Если тело "
            "выделено отдельно — только тело. ПОЛОЖИТЕЛЬНОЕ число. "
            "В ИСХОДНЫХ единицах."
        ),
    )
    lease_interest: Optional[float] = Field(
        None,
        description=(
            "Проценты по аренде ТОЛЬКО если в ОДДС/примечании есть ОТДЕЛЬНАЯ "
            "строка ('Проценты по аренде уплаченные', 'Interest on lease "
            "liabilities'). Если аренда одной строкой без разбивки — null, "
            "не выдумывай. ПОЛОЖИТЕЛЬНОЕ число. В ИСХОДНЫХ единицах."
        ),
    )

    depreciation_amortization: Optional[float] = Field(
        None,
        description=(
            "Амортизация основных средств, НМА и права пользования активом "
            "(D&A) за период. Ищи в разделе ОПЕРАЦИОННОЙ деятельности ОДДС "
            "как корректировку прибыли, либо в примечании о себестоимости / "
            "операционных расходах. СИНОНИМЫ: 'Амортизация', 'Износ и "
            "амортизация', 'Амортизация основных средств и нематериальных "
            "активов', 'Depreciation and amortisation', 'Depreciation, "
            "depletion and amortisation'. Если амортизация ОС, НМА и права "
            "пользования (аренда по МСФО 16) указаны раздельными строками — "
            "СЛОЖИ их и отметь разбивку в extraction_notes. Записывай "
            "ПОЛОЖИТЕЛЬНЫМ числом, даже если в ОДДС она со знаком плюс как "
            "корректировка. В ИСХОДНЫХ единицах."
        ),
    )
    debt_principal: Optional[float] = Field(
        None,
        description=(
            "Оставь null. Погашение кредитов/займов/облигаций сейчас не "
            "извлекаем и в FCF не входит (финансирование, не sustenance). "
            "Не суммируй строки погашения долга в другие поля."
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
            "Чистая прибыль акционеров материнской компании. По умолчанию = "
            "net_income_reported (та же строка ОПиУ). Оба поля заполняй; "
            "не оставляй одно null, если второе известно."
        ),
    )
    net_income_reported: Optional[float] = Field(
        None,
        description=(
            "Отчётная чистая прибыль из строки 'Чистая прибыль' / 'Прибыль за "
            "период' без корректировок. Если заполнил net_income — скопируй "
            "сюда то же число (и наоборот)."
        ),
    )

    # ─── Дивиденды ──────────────────────────────────────────────────────────
    dividends_per_share: Optional[float] = Field(
        None,
        description=(
            "Сумма дивидендов на одну обыкновенную акцию за ОТЧЁТНЫЙ ГОД "
            "(промежуточные + финальные транши этого года) в ПОЛНЫХ единицах "
            "валюты (₽/$). Финальный дивиденд за год N часто объявляют/платят "
            "в году N+1 — относи к году N, не к году платежа. Не подставляй "
            "дивиденд прошлого года. Если полный итог за отчётный год ещё не "
            "объявлен — null."
        ),
    )
    dividends_paid: bool = Field(
        False, description="Выплачивались ли дивиденды в отчётном периоде"
    )

    @field_validator("dividends_paid", mode="before")
    @classmethod
    def _coerce_dividends_paid(cls, v):
        """json_object-режим часто отдаёт null вместо false — не валим весь ответ."""
        if v is None:
            return False
        return v
    special_dividends_per_share: Optional[float] = Field(
        None,
        description=(
            "ЧАСТЬ dividends_per_share, которая является РАЗОВОЙ выплатой и не "
            "повторится в следующем году. Это специальный дивиденд, доплата за "
            "пропущенные периоды, распределение выручки от продажи актива или "
            "бизнеса, разовое распределение от материнской компании. Признаки в "
            "тексте: 'специальный дивиденд', 'special dividend', 'разовая "
            "выплата', 'дополнительный дивиденд за 20XX год', 'в связи с "
            "продажей'. ВАЖНО: это не отдельная сумма СВЕРХ dividends_per_share, "
            "а её составляющая, поэтому значение не может превышать "
            "dividends_per_share. Если в отчёте нет прямого указания на разовый "
            "характер выплаты — оставь null, НЕ угадывай. В ПОЛНЫХ единицах "
            "валюты (₽/$) на одну обыкновенную акцию."
        ),
    )
    # Без max_length: в json_schema-режиме OpenAI строковые ограничения
    # поддерживаются не всеми провайдерами и запрос падает на валидации схемы.
    # Обрезаем длину на нашей стороне, в _sanitize_special_dividends.
    special_dividends_note: Optional[str] = Field(
        None,
        description=(
            "Одна короткая фраза о причине разовой выплаты, если "
            "special_dividends_per_share заполнен: например 'доплата за 2021 "
            "год' или 'распределение от продажи зарубежного бизнеса'. "
            "null, если разовой части нет."
        ),
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

    @field_validator("shares_outstanding", mode="before")
    @classmethod
    def _coerce_shares_outstanding_int(cls, v):
        """LLM иногда отдаёт млн акций как float (178.38) — округляем до int.

        Иначе Pydantic падает с int_from_float до auto-fix масштаба.
        """
        if v is None or v == "":
            return None
        if isinstance(v, bool):
            return None
        if isinstance(v, int):
            return v
        if isinstance(v, float):
            if v != v:  # NaN
                return None
            return int(round(v))
        if isinstance(v, str):
            text = v.strip().replace(" ", "").replace("\u00a0", "").replace(",", ".")
            if not text or text.lower() in {"null", "none", "n/a", "-"}:
                return None
            try:
                return int(round(float(text)))
            except ValueError:
                return v
        return v

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

    @field_validator("shares_units_scale", mode="before")
    @classmethod
    def _coerce_shares_units_scale(cls, v):
        """null от модели → units (безопасный дефолт, дальше сработают auto-fix)."""
        if v is None or (isinstance(v, str) and not v.strip()):
            return "units"
        return v

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
    "debt_principal",
    "depreciation_amortization",
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

    Поля, которые всегда в полных единицах валюты (dividends_per_share,
    special_dividends_per_share), НЕ трогаем.
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


class ExtractedCompanyDescription(BaseModel):
    """Результат LLM-извлечения описания компании из примечаний отчёта."""

    description: Optional[str] = Field(
        None,
        description=(
            "Сжатое описание деятельности компании из раздела "
            "«1. Информация о компании». null, если раздел пуст или не найден."
        ),
    )
