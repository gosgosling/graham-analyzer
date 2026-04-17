"""Пайплайн: PDF → текст → LLM → валидация → запись отчёта в БД.

Используется:
  * эндпоинтом POST /reports/parse-pdf (в reports_router.py),
  * CLI-утилитой tools/report-parser/main.py.

Для LLM используется `app.config.settings` (LLM_*).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Union

from sqlalchemy.orm import Session

from app.config import settings
from app.models.company import Company
from app.models.enums import sector_to_report_type
from app.models.financial_report import FinancialReport
from app.schemas import FinancialReportCreate
from app.services.reports import report_service
from app.services.report_parser.llm_client import (
    LLMNotConfiguredError,
    LLMParseError,
    LLMTransientError,
    extract_report_via_llm,
)
from app.services.report_parser.pdf_extractor import (
    PdfExtractionResult,
    extract_financial_pages,
)
from app.services.report_parser.prompts import build_system_prompt, build_user_prompt
from app.services.report_parser.schemas import ExtractedReport, rescale_to_millions

logger = logging.getLogger(__name__)


# ─── Описание сравниваемых полей ─────────────────────────────────────────────


@dataclass(frozen=True)
class _FieldSpec:
    """Одно поле отчёта — как его сравнивать и показывать."""
    key: str                    # имя атрибута в FinancialReport И в ExtractedReport
    label: str                  # человеко-читаемое имя
    kind: str                   # 'money_mln' | 'int' | 'float' | 'bool' | 'str' | 'date'
    relevant_for: tuple[str, ...] = ("general", "bank")  # general/bank


# Поля, которые есть и в модели БД, и в ExtractedReport — значит их реально
# можно сравнивать. Порядок важен — в таком порядке покажем в UI.
_COMPARABLE_FIELDS: tuple[_FieldSpec, ...] = (
    _FieldSpec("report_date", "Дата окончания периода", "date"),
    _FieldSpec("filing_date", "Дата публикации", "date"),
    _FieldSpec("currency", "Валюта", "str"),
    _FieldSpec("shares_outstanding", "Акции в обращении", "int"),
    _FieldSpec("revenue", "Выручка / Опер. доходы", "money_mln"),
    _FieldSpec("net_income", "Чистая прибыль", "money_mln"),
    _FieldSpec("net_income_reported", "Прибыль (отчётная)", "money_mln"),
    _FieldSpec("total_assets", "Активы (всего)", "money_mln"),
    _FieldSpec("current_assets", "Оборотные активы", "money_mln", ("general",)),
    _FieldSpec("total_liabilities", "Обязательства (всего)", "money_mln"),
    _FieldSpec("current_liabilities", "Краткосрочные обязательства", "money_mln", ("general",)),
    _FieldSpec("equity", "Собственный капитал", "money_mln"),
    _FieldSpec("dividends_per_share", "Дивиденд на акцию", "float"),
    _FieldSpec("dividends_paid", "Дивиденды выплачивались", "bool"),
    _FieldSpec("net_interest_income", "Чистые проц. доходы (NII)", "money_mln", ("bank",)),
    _FieldSpec("fee_commission_income", "Чистые комисс. доходы", "money_mln", ("bank",)),
    _FieldSpec("operating_expenses", "Операционные расходы", "money_mln", ("bank",)),
    _FieldSpec("provisions", "Резервы под обесценение", "money_mln", ("bank",)),
)


_MATERIAL_MONEY_THRESHOLD_MLN = 1.0  # разница в < 1 млн не считаем значимой
_MATERIAL_PCT_THRESHOLD = 0.5        # < 0.5% — это копейки округления

Status = str  # 'match' | 'close' | 'mismatch' | 'missing_ai' | 'missing_existing' | 'both_missing'


@dataclass
class ReportFieldDiff:
    """Diff по одному полю — что было, что извлекла модель, насколько совпало."""
    field: str
    label: str
    kind: str
    existing_value: Any
    extracted_value: Any
    abs_diff: Optional[float] = None     # |A - B|, только для числовых
    pct_diff: Optional[float] = None     # (A - B) / A * 100, знак = насколько модель ЗАВЫСИЛА
    status: Status = "match"
    note: Optional[str] = None


@dataclass
class ComparisonSummary:
    """Общая сводка по сравнению."""
    total_fields: int = 0
    matched: int = 0
    close: int = 0          # числа отличаются < 1%, но не 0
    mismatched: int = 0
    missing_in_ai: int = 0  # у аналитика значение есть, AI не нашёл
    missing_in_existing: int = 0  # у AI значение есть, у аналитика не заполнено
    both_missing: int = 0
    max_pct_diff: Optional[float] = None


@dataclass
class ComparisonResult:
    """Результат режима сравнения (compare-only, без записи в БД)."""
    ticker: str
    fiscal_year: int
    report_type: str
    existing_report_id: int
    existing_report_verified: bool
    extracted: ExtractedReport
    diffs: list[ReportFieldDiff] = field(default_factory=list)
    summary: ComparisonSummary = field(default_factory=ComparisonSummary)
    pdf_label: str = ""
    selected_pages: int = 0
    total_pages: int = 0


# ─── Результат ────────────────────────────────────────────────────────────────


@dataclass
class ExtractionOutcome:
    """Что получилось после обработки одного PDF."""
    ticker: str
    fiscal_year: int
    report_type: str  # 'general' | 'bank'
    dry_run: bool
    pdf_label: str
    skipped_reason: Optional[str] = None
    created_report_id: Optional[int] = None
    extracted: Optional[ExtractedReport] = None
    selected_pages: int = 0
    total_pages: int = 0

    @property
    def success(self) -> bool:
        return self.skipped_reason is None and (
            self.dry_run or self.created_report_id is not None
        )


# ─── Исключения ──────────────────────────────────────────────────────────────


class ReportAlreadyExistsError(RuntimeError):
    """В БД уже есть отчёт с такими ключевыми атрибутами (без --force)."""

    def __init__(self, report_id: int):
        super().__init__(
            f"Отчёт уже существует в БД (id={report_id}). "
            f"Используй force=True чтобы пересоздать."
        )
        self.report_id = report_id


# ─── Вспомогательные ─────────────────────────────────────────────────────────


def _resolve_report_date(extracted: ExtractedReport) -> str:
    """Если модель не смогла извлечь report_date — подставим 31.12 года."""
    if extracted.report_date:
        return extracted.report_date
    return f"{extracted.fiscal_year}-12-31"


def _build_extraction_notes(
    extracted: ExtractedReport,
    pdf_label: str,
    selected_pages: int,
    total_pages: int,
) -> str:
    """Собрать финальный extraction_notes с техническими метаданными + заметки модели."""
    header = (
        f"[AUTO-EXTRACTED | model={settings.extraction_model_label} | "
        f"pdf={pdf_label} | pages_used={selected_pages}/{total_pages} | "
        f"scale_in_pdf={extracted.units_scale} | confidence={extracted.confidence or 'n/a'}]"
    )
    model_notes = (extracted.extraction_notes or "").strip()
    warnings: list[str] = []

    if extracted.net_income is None:
        warnings.append("net_income не найден — требует ручной проверки")
    if extracted.equity is None:
        warnings.append("equity не найден — требует ручной проверки")
    if extracted.report_type == "bank":
        if extracted.revenue is None:
            warnings.append(
                "revenue (Total Operating Income) не найден — ОБЯЗАТЕЛЬНО проверить"
            )
    else:
        if extracted.current_assets is None or extracted.current_liabilities is None:
            warnings.append(
                "current_assets/current_liabilities не найдены — проверить баланс"
            )

    parts = [header]
    if model_notes:
        parts.append("Заметки модели:\n" + model_notes)
    if warnings:
        parts.append("Флаги для проверки:\n- " + "\n- ".join(warnings))

    return "\n\n".join(parts)


def _find_existing_report(
    db: Session,
    *,
    company_id: int,
    fiscal_year: int,
    fiscal_quarter: Optional[int],
    period_type: str,
    accounting_standard: str,
    consolidated: bool,
) -> Optional[FinancialReport]:
    q = (
        db.query(FinancialReport)
        .filter(FinancialReport.company_id == company_id)
        .filter(FinancialReport.fiscal_year == fiscal_year)
        .filter(FinancialReport.period_type == period_type)
        .filter(FinancialReport.accounting_standard == accounting_standard)
        .filter(FinancialReport.consolidated.is_(consolidated))
    )
    if fiscal_quarter is None:
        q = q.filter(FinancialReport.fiscal_quarter.is_(None))
    else:
        q = q.filter(FinancialReport.fiscal_quarter == fiscal_quarter)
    return q.first()


# ─── Основной пайплайн для одного PDF ────────────────────────────────────────


def parse_pdf_to_report(
    db: Session,
    *,
    pdf_source: Union[Path, bytes],
    company: Company,
    fiscal_year: int,
    dry_run: bool = False,
    force: bool = False,
    period_type: str = "annual",
    fiscal_quarter: Optional[int] = None,
    accounting_standard: str = "IFRS",
    consolidated: bool = True,
    source_pdf_path: Optional[str] = None,
    pdf_label: Optional[str] = None,
) -> ExtractionOutcome:
    """
    Прогнать PDF через AI-пайплайн и (при dry_run=False) создать FinancialReport
    с auto_extracted=True и verified_by_analyst=False.

    Args:
        db: открытая сессия SQLAlchemy.
        pdf_source: либо путь к PDF, либо байты (например, из UploadFile).
        company: ORM-объект Company (должен существовать в БД).
        fiscal_year: ожидаемый год отчёта.
        dry_run: если True — только показать результат, не писать в БД.
        force: если True — удалить существующий отчёт и создать заново.
        period_type/fiscal_quarter/accounting_standard/consolidated — атрибуты,
            определяющие уникальный ключ отчёта.
        source_pdf_path: что записать в `financial_reports.source_pdf_path`.
        pdf_label: человекочитаемое имя PDF для логов и заметок (если передали bytes).

    Raises:
        ReportAlreadyExistsError: если отчёт уже есть и force=False.
        LLMNotConfiguredError: если не настроен LLM.
        LLMParseError: если LLM вернул невалидные данные.
        RuntimeError: если PDF не содержит финансовых таблиц.
    """
    resolved_report_type = sector_to_report_type(company.sector)

    if isinstance(pdf_source, Path):
        label = pdf_label or pdf_source.name
        if not source_pdf_path:
            source_pdf_path = str(pdf_source)
    else:
        label = pdf_label or "uploaded.pdf"

    outcome = ExtractionOutcome(
        ticker=company.ticker,  # type: ignore[arg-type]
        fiscal_year=fiscal_year,
        report_type=resolved_report_type,
        dry_run=dry_run,
        pdf_label=label,
    )

    # 1) Дубликат?
    existing = _find_existing_report(
        db,
        company_id=company.id,  # type: ignore[arg-type]
        fiscal_year=fiscal_year,
        fiscal_quarter=fiscal_quarter,
        period_type=period_type,
        accounting_standard=accounting_standard,
        consolidated=consolidated,
    )
    if existing and not force:
        raise ReportAlreadyExistsError(existing.id)  # type: ignore[arg-type]

    # 2) Выбор релевантных страниц PDF
    extraction: PdfExtractionResult = extract_financial_pages(
        pdf_source, pdf_label=label
    )
    outcome.selected_pages = len(extraction.selected_pages)
    outcome.total_pages = extraction.total_pages

    # 3) Промпты
    system_prompt = build_system_prompt(resolved_report_type)
    user_prompt = build_user_prompt(
        ticker=company.ticker,  # type: ignore[arg-type]
        expected_year=fiscal_year,
        company_name=company.name,  # type: ignore[arg-type]
        sector=company.sector,  # type: ignore[arg-type]
        pdf_text=extraction.text,
    )

    # 4) Вызов LLM (исключения LLMNotConfiguredError/LLMParseError/LLMTransientError
    #    поднимутся наружу — их ловит вызывающий код).
    extracted = extract_report_via_llm(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
    )

    # 5) Конвертация единиц в миллионы
    extracted = rescale_to_millions(extracted)

    # 5.1) Санити-чек: совпадает ли fiscal_year
    if extracted.fiscal_year != fiscal_year:
        logger.warning(
            "[%s %s] LLM вернул fiscal_year=%d, ожидали %d. Форсируем ожидаемый.",
            company.ticker, fiscal_year, extracted.fiscal_year, fiscal_year,
        )
        extracted = extracted.model_copy(update={"fiscal_year": fiscal_year})

    outcome.extracted = extracted

    # 6) Соберём extraction_notes
    notes = _build_extraction_notes(
        extracted=extracted,
        pdf_label=label,
        selected_pages=len(extraction.selected_pages),
        total_pages=extraction.total_pages,
    )

    # 7) Для банка NULL'им current_assets/current_liabilities.
    ca = extracted.current_assets
    cl = extracted.current_liabilities
    if resolved_report_type == "bank":
        ca = None
        cl = None

    payload = FinancialReportCreate(
        company_id=company.id,  # type: ignore[arg-type]
        period_type=period_type,  # type: ignore[arg-type]
        fiscal_year=fiscal_year,
        fiscal_quarter=fiscal_quarter,
        accounting_standard=accounting_standard,  # type: ignore[arg-type]
        consolidated=consolidated,
        source="company_website",  # type: ignore[arg-type]
        report_date=_resolve_report_date(extracted),
        filing_date=extracted.filing_date,
        price_per_share=None,
        price_at_filing=None,
        shares_outstanding=extracted.shares_outstanding,
        revenue=extracted.revenue,
        net_income=extracted.net_income,
        net_income_reported=extracted.net_income_reported,
        total_assets=extracted.total_assets,
        current_assets=ca,
        total_liabilities=extracted.total_liabilities,
        current_liabilities=cl,
        equity=extracted.equity,
        dividends_per_share=extracted.dividends_per_share,
        dividends_paid=extracted.dividends_paid,
        net_interest_income=extracted.net_interest_income,
        fee_commission_income=extracted.fee_commission_income,
        operating_expenses=extracted.operating_expenses,
        provisions=extracted.provisions,
        currency=extracted.currency,
        exchange_rate=None,
        auto_extracted=True,
        verified_by_analyst=False,
        extraction_notes=notes,
        extraction_model=settings.extraction_model_label,
        source_pdf_path=source_pdf_path,
    )

    if dry_run:
        logger.info(
            "[DRY-RUN %s %s] revenue=%s net_income=%s equity=%s assets=%s "
            "liabilities=%s report_type=%s currency=%s",
            company.ticker, fiscal_year,
            extracted.revenue, extracted.net_income, extracted.equity,
            extracted.total_assets, extracted.total_liabilities,
            resolved_report_type, extracted.currency,
        )
        return outcome

    # 8) Запись в БД (при force удаляем старую версию)
    if existing and force:
        logger.warning(
            "[%s %s] Пересоздаём отчёт (id=%d, force=True).",
            company.ticker, fiscal_year, existing.id,
        )
        db.delete(existing)
        db.commit()

    created = report_service.create_report(db=db, report_data=payload)
    outcome.created_report_id = created.id  # type: ignore[assignment]
    logger.info(
        "[%s %s] Создан черновик отчёта id=%s (auto_extracted=True, verified=False).",
        company.ticker, fiscal_year, created.id,
    )
    return outcome


# ─── Режим сравнения с уже существующим отчётом ─────────────────────────────


def _normalize_date(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        return value[:10]  # берём только YYYY-MM-DD
    if hasattr(value, "isoformat"):
        return value.isoformat()[:10]
    return str(value)[:10]


def _to_float(value: Any) -> Optional[float]:
    """Привести значение из БД (Decimal / int / float) к float, либо None."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _compute_money_status(
    existing_raw: Any, extracted_raw: Any
) -> tuple[Status, Optional[float], Optional[float], Optional[str]]:
    """Статус для денежного поля (в миллионах). Возвращает (status, abs, pct, note)."""
    existing = _to_float(existing_raw)
    extracted = _to_float(extracted_raw)
    if existing is None and extracted is None:
        return "both_missing", None, None, None
    if existing is None and extracted is not None:
        return "missing_existing", None, None, "Аналитик не заполнил — модель предложила значение"
    if existing is not None and extracted is None:
        return "missing_ai", None, None, "Модель НЕ извлекла значение — требует внимания"

    assert existing is not None and extracted is not None
    abs_d = abs(existing - extracted)
    base = abs(existing) if existing != 0 else max(abs(extracted), 1.0)
    pct = (extracted - existing) / base * 100.0

    if abs_d < _MATERIAL_MONEY_THRESHOLD_MLN and abs(pct) < _MATERIAL_PCT_THRESHOLD:
        return "match", abs_d, pct, None
    if abs(pct) < 1.0:
        return "close", abs_d, pct, "Разница < 1% (округление / переоценка)"
    return "mismatch", abs_d, pct, None


def _compute_generic_status(
    existing: Any, extracted: Any, kind: str
) -> tuple[Status, Optional[float], Optional[float], Optional[str]]:
    """Статус для нечисловых / небольших числовых полей."""
    if kind == "date":
        e = _normalize_date(existing)
        x = _normalize_date(extracted)
        if e is None and x is None:
            return "both_missing", None, None, None
        if e is None:
            return "missing_existing", None, None, None
        if x is None:
            return "missing_ai", None, None, None
        return ("match" if e == x else "mismatch"), None, None, None

    if kind == "bool":
        e = None if existing is None else bool(existing)
        x = None if extracted is None else bool(extracted)
        if e is None and x is None:
            return "both_missing", None, None, None
        if e is None:
            return "missing_existing", None, None, None
        if x is None:
            return "missing_ai", None, None, None
        return ("match" if e == x else "mismatch"), None, None, None

    if kind == "str":
        e = (existing or "").strip() if isinstance(existing, str) else existing
        x = (extracted or "").strip() if isinstance(extracted, str) else extracted
        if e is None and x is None:
            return "both_missing", None, None, None
        if e is None:
            return "missing_existing", None, None, None
        if x is None:
            return "missing_ai", None, None, None
        return ("match" if str(e).upper() == str(x).upper() else "mismatch"), None, None, None

    # int / float (не деньги) — считаем как деньги, но без единиц
    e_f = _to_float(existing)
    x_f = _to_float(extracted)
    if e_f is None and x_f is None:
        return "both_missing", None, None, None
    if e_f is None:
        return "missing_existing", None, None, None
    if x_f is None:
        return "missing_ai", None, None, None

    abs_d = abs(e_f - x_f)
    base = abs(e_f) if e_f != 0 else max(abs(x_f), 1.0)
    pct = (x_f - e_f) / base * 100.0
    if abs_d < 1e-6 or abs(pct) < _MATERIAL_PCT_THRESHOLD:
        return "match", abs_d, pct, None
    if abs(pct) < 1.0:
        return "close", abs_d, pct, None
    return "mismatch", abs_d, pct, None


def compute_report_diff(
    existing: FinancialReport,
    extracted: ExtractedReport,
    *,
    report_type: str,
) -> tuple[list[ReportFieldDiff], ComparisonSummary]:
    """
    Поле за полем сравнить существующий (ручной) отчёт с AI-извлечением.

    Только поля, имеющие смысл для данного `report_type` (general / bank).
    """
    diffs: list[ReportFieldDiff] = []
    summary = ComparisonSummary()
    max_pct: Optional[float] = None

    for spec in _COMPARABLE_FIELDS:
        if report_type not in spec.relevant_for:
            continue

        existing_raw = getattr(existing, spec.key, None)
        extracted_raw = getattr(extracted, spec.key, None)

        if spec.kind == "money_mln":
            status, abs_d, pct, note = _compute_money_status(
                existing_raw, extracted_raw
            )
        else:
            status, abs_d, pct, note = _compute_generic_status(
                existing_raw, extracted_raw, spec.kind
            )

        diffs.append(
            ReportFieldDiff(
                field=spec.key,
                label=spec.label,
                kind=spec.kind,
                existing_value=existing_raw,
                extracted_value=extracted_raw,
                abs_diff=abs_d,
                pct_diff=pct,
                status=status,
                note=note,
            )
        )

        summary.total_fields += 1
        if status == "match":
            summary.matched += 1
        elif status == "close":
            summary.close += 1
        elif status == "mismatch":
            summary.mismatched += 1
        elif status == "missing_ai":
            summary.missing_in_ai += 1
        elif status == "missing_existing":
            summary.missing_in_existing += 1
        elif status == "both_missing":
            summary.both_missing += 1

        if pct is not None:
            if max_pct is None or abs(pct) > abs(max_pct):
                max_pct = pct

    summary.max_pct_diff = max_pct
    return diffs, summary


def compare_pdf_with_existing(
    db: Session,
    *,
    pdf_source: Union[Path, bytes],
    company: Company,
    fiscal_year: int,
    period_type: str = "annual",
    fiscal_quarter: Optional[int] = None,
    accounting_standard: str = "IFRS",
    consolidated: bool = True,
    pdf_label: Optional[str] = None,
) -> ComparisonResult:
    """
    Прогнать PDF через LLM и сравнить с уже существующим отчётом в БД
    БЕЗ каких-либо изменений в БД. Полезно для оценки качества модели
    на уже подтверждённых аналитиком отчётах.

    Raises:
        ReportNotFoundForComparison: если отчёта для сравнения ещё нет.
        LLMNotConfiguredError / LLMParseError / LLMTransientError: см. parse_pdf_to_report.
        RuntimeError: если PDF не содержит финансовых таблиц.
    """
    resolved_report_type = sector_to_report_type(company.sector)

    if isinstance(pdf_source, Path):
        label = pdf_label or pdf_source.name
    else:
        label = pdf_label or "uploaded.pdf"

    existing = _find_existing_report(
        db,
        company_id=company.id,  # type: ignore[arg-type]
        fiscal_year=fiscal_year,
        fiscal_quarter=fiscal_quarter,
        period_type=period_type,
        accounting_standard=accounting_standard,
        consolidated=consolidated,
    )
    if not existing:
        raise ReportNotFoundForComparison(
            f"В БД нет отчёта {company.ticker} {fiscal_year} ({period_type}, "
            f"{accounting_standard}) для сравнения. Используйте обычный upload."
        )

    extraction: PdfExtractionResult = extract_financial_pages(pdf_source, pdf_label=label)

    system_prompt = build_system_prompt(resolved_report_type)
    user_prompt = build_user_prompt(
        ticker=company.ticker,  # type: ignore[arg-type]
        expected_year=fiscal_year,
        company_name=company.name,  # type: ignore[arg-type]
        sector=company.sector,  # type: ignore[arg-type]
        pdf_text=extraction.text,
    )

    extracted = extract_report_via_llm(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
    )
    extracted = rescale_to_millions(extracted)
    if extracted.fiscal_year != fiscal_year:
        extracted = extracted.model_copy(update={"fiscal_year": fiscal_year})

    diffs, summary = compute_report_diff(
        existing, extracted, report_type=resolved_report_type
    )

    logger.info(
        "[COMPARE %s %s] existing_id=%s matched=%d/%d mismatched=%d missing_ai=%d max_pct=%s",
        company.ticker, fiscal_year, existing.id,
        summary.matched, summary.total_fields, summary.mismatched,
        summary.missing_in_ai,
        f"{summary.max_pct_diff:+.2f}%" if summary.max_pct_diff is not None else "n/a",
    )

    return ComparisonResult(
        ticker=company.ticker,  # type: ignore[arg-type]
        fiscal_year=fiscal_year,
        report_type=resolved_report_type,
        existing_report_id=existing.id,  # type: ignore[arg-type]
        existing_report_verified=bool(existing.verified_by_analyst),
        extracted=extracted,
        diffs=diffs,
        summary=summary,
        pdf_label=label,
        selected_pages=len(extraction.selected_pages),
        total_pages=extraction.total_pages,
    )


class ReportNotFoundForComparison(RuntimeError):
    """Нет существующего отчёта в БД — с чем сравнивать нечего."""


__all__ = (
    "ComparisonResult",
    "ComparisonSummary",
    "ExtractionOutcome",
    "LLMNotConfiguredError",
    "LLMParseError",
    "LLMTransientError",
    "ReportAlreadyExistsError",
    "ReportFieldDiff",
    "ReportNotFoundForComparison",
    "compare_pdf_with_existing",
    "compute_report_diff",
    "parse_pdf_to_report",
)
