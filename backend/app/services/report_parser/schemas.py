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

from pydantic import BaseModel, Field


ReportTypeLiteral = Literal["general", "bank"]
PeriodTypeLiteral = Literal["annual", "quarterly", "semi_annual"]
AccountingStandardLiteral = Literal["IFRS", "RAS", "US_GAAP", "UK_GAAP", "OTHER"]


class ExtractedReport(BaseModel):
    """Структурированный результат извлечения из одного PDF."""

    # ─── Идентификация периода ───────────────────────────────────────────────
    fiscal_year: int = Field(..., description="Отчётный год, например 2023")
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
    report_date: str = Field(
        ...,
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
    "revenue",
    "net_income",
    "net_income_reported",
    "net_interest_income",
    "fee_commission_income",
    "operating_expenses",
    "provisions",
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
