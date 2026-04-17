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
    total_assets: Optional[float] = Field(None, description="Итого активы")
    total_liabilities: Optional[float] = Field(None, description="Итого обязательства")
    current_assets: Optional[float] = Field(
        None,
        description="Итого оборотные активы (не заполнять для банков — оставить null)",
    )
    current_liabilities: Optional[float] = Field(
        None,
        description="Итого краткосрочные обязательства (не заполнять для банков)",
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
            "Количество обыкновенных акций в обращении, в штуках (weighted average "
            "или на конец периода — смотри что указано, предпочтение средневзвешенному)."
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


def rescale_to_millions(report: ExtractedReport) -> ExtractedReport:
    """
    Привести монетарные поля к миллионам валюты в соответствии с `units_scale`.

    После вызова `units_scale` установлено в `millions`, а числа в соответствующих
    полях уже выражены в млн.

    Поля, которые всегда в полных единицах (dividends_per_share, shares_outstanding),
    НЕ трогаем.
    """
    factor = _SCALE_TO_MILLIONS.get(report.units_scale, 1.0)
    if factor == 1.0:
        return report

    data = report.model_dump()
    for field in _MONETARY_FIELDS_IN_MILLIONS:
        value = data.get(field)
        if value is not None:
            data[field] = float(value) * factor
    data["units_scale"] = "millions"
    return ExtractedReport.model_validate(data)
