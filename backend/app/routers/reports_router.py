import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import List, Optional, Dict

from app.config import settings
from app.database import get_db
from app.models.company import Company
from app.schemas import FinancialReport, FinancialReportCreate
from app.services.reports import report_service
from app.services.report_parser import (
    compare_pdf_with_existing,
    parse_pdf_to_report,
)
from app.services.report_parser.extractor_service import (
    ReportAlreadyExistsError,
    ReportNotFoundForComparison,
)
from app.services.report_parser.llm_client import (
    LLMNotConfiguredError,
    LLMParseError,
    LLMTransientError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reports", tags=["reports"])


@router.post("/", response_model=FinancialReport, status_code=status.HTTP_201_CREATED)
def create_financial_report(
    report_data: FinancialReportCreate,
    db: Session = Depends(get_db)
):
    """Создать новый финансовый отчет."""
    try:
        return report_service.create_report(db=db, report_data=report_data)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Ошибка при создании отчета: {str(e)}"
        )


@router.get("/", response_model=List[FinancialReport])
def get_all_reports(
    skip: int = 0,
    limit: int = 200,
    db: Session = Depends(get_db)
):
    """Получить все финансовые отчеты (с пагинацией)."""
    return report_service.get_all_reports(db=db, skip=skip, limit=limit)


@router.get("/{report_id}", response_model=FinancialReport)
def get_report(report_id: int, db: Session = Depends(get_db)):
    """
    Получить финансовый отчет по ID.
    
    Автоматически возвращает конвертированные значения в рублях через поля *_rub.
    Если отчет в USD, то поля price_per_share_rub, revenue_rub и т.д. будут содержать
    значения умноженные на exchange_rate.
    """
    report = report_service.get_report_by_id(db=db, report_id=report_id)
    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Отчет с ID {report_id} не найден"
        )
    return report


@router.get("/company/{company_id}", response_model=List[FinancialReport])
def get_company_reports(
    company_id: int,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """Получить все отчеты для конкретной компании."""
    return report_service.get_reports_by_company(
        db=db,
        company_id=company_id,
        skip=skip,
        limit=limit
    )


@router.get("/company/{company_id}/latest", response_model=FinancialReport)
def get_latest_company_report(company_id: int, db: Session = Depends(get_db)):
    """Получить последний отчет для компании."""
    report = report_service.get_latest_report(db=db, company_id=company_id)
    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Отчеты для компании с ID {company_id} не найдены"
        )
    return report


@router.put("/{report_id}", response_model=FinancialReport)
def update_financial_report(
    report_id: int,
    report_data: FinancialReportCreate,
    db: Session = Depends(get_db)
):
    """Обновить существующий финансовый отчет."""
    updated_report = report_service.update_report(
        db=db,
        report_id=report_id,
        report_data=report_data
    )
    if not updated_report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Отчет с ID {report_id} не найден"
        )
    return updated_report


@router.delete("/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_financial_report(report_id: int, db: Session = Depends(get_db)):
    """Удалить финансовый отчет."""
    success = report_service.delete_report(db=db, report_id=report_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Отчет с ID {report_id} не найден"
        )
    return None


# ─── Верификация отчётов (AI-парсер vs аналитик) ───────────────────────────


@router.get("/unverified/list", response_model=List[FinancialReport])
def list_unverified_reports(
    company_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 200,
    db: Session = Depends(get_db),
):
    """
    Вернуть список отчётов, НЕ проверенных финансовым аналитиком
    (verified_by_analyst=False). Это в первую очередь отчёты, созданные
    AI-парсером из PDF, которые ждут подтверждения.
    """
    return report_service.get_unverified_reports(
        db=db, company_id=company_id, skip=skip, limit=limit
    )


@router.get("/unverified/counts", response_model=Dict[int, int])
def unverified_counts_by_company(db: Session = Depends(get_db)):
    """
    Вернуть словарь {company_id: count} с количеством непроверенных отчётов
    у каждой компании. Используется фронтом, чтобы подсветить компании
    с неподтверждёнными данными.
    """
    return report_service.count_unverified_by_company(db=db)


@router.post("/{report_id}/verify", response_model=FinancialReport)
def verify_report(report_id: int, db: Session = Depends(get_db)):
    """
    Отметить отчёт как проверенный финансовым аналитиком
    (verified_by_analyst=True, verified_at=now).
    """
    updated = report_service.mark_report_verified(db=db, report_id=report_id)
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Отчет с ID {report_id} не найден",
        )
    return updated


@router.post("/{report_id}/unverify", response_model=FinancialReport)
def unverify_report(report_id: int, db: Session = Depends(get_db)):
    """
    Снять отметку проверки — вернуть отчёт в статус «требует проверки».
    """
    updated = report_service.mark_report_unverified(db=db, report_id=report_id)
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Отчет с ID {report_id} не найден",
        )
    return updated


# ─── AI-парсер PDF-отчётов ─────────────────────────────────────────────────


class ParsePdfResponse(BaseModel):
    """Ответ эндпоинта /reports/parse-pdf."""
    report: FinancialReport
    auto_extracted: bool = True
    extraction_model: str
    selected_pages: int
    total_pages: int
    warnings: List[str] = []


class LlmStatusResponse(BaseModel):
    """Статус настройки LLM (для фронта: показывать ли форму загрузки)."""
    configured: bool
    provider: str
    model: str
    base_url: str


@router.get("/ai/status", response_model=LlmStatusResponse)
def llm_status():
    """Показать, сконфигурирован ли LLM для AI-парсинга отчётов."""
    return LlmStatusResponse(
        configured=settings.llm_configured,
        provider=settings.LLM_PROVIDER,
        model=settings.LLM_MODEL,
        base_url=settings.LLM_BASE_URL,
    )


@router.post("/parse-pdf", response_model=ParsePdfResponse, status_code=status.HTTP_201_CREATED)
async def parse_pdf_endpoint(
    company_id: int = Form(..., description="ID компании из таблицы companies"),
    fiscal_year: int = Form(..., description="Отчётный год"),
    period_type: str = Form("annual", description="annual | quarterly | semi_annual"),
    fiscal_quarter: Optional[int] = Form(None, description="1..4 для квартальных"),
    accounting_standard: str = Form("IFRS", description="IFRS | RAS | US_GAAP | ..."),
    consolidated: bool = Form(True),
    force: bool = Form(False, description="Пересоздать, если отчёт уже есть"),
    file: UploadFile = File(..., description="PDF-файл отчёта"),
    db: Session = Depends(get_db),
):
    """
    Загрузить PDF годового отчёта и автоматически создать черновик
    `FinancialReport` через LLM.

    Созданный отчёт помечается `auto_extracted=True, verified_by_analyst=False`.
    В поле `extraction_notes` кладутся замечания модели + автоматические флаги
    для проверки (какие значения не нашлись и т.п.).

    После ручной проверки подтвердите отчёт через `POST /reports/{id}/verify`
    или сохраните его в обычной веб-форме.
    """
    if not settings.llm_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "LLM не сконфигурирован. Задайте LLM_API_KEY / LLM_MODEL "
                "в корневом .env проекта и перезапустите backend."
            ),
        )

    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Компания с ID {company_id} не найдена",
        )

    filename = file.filename or "uploaded.pdf"
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ожидается файл с расширением .pdf",
        )

    pdf_bytes = await file.read()
    if not pdf_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Передан пустой файл",
        )

    try:
        outcome = parse_pdf_to_report(
            db=db,
            pdf_source=pdf_bytes,
            company=company,
            fiscal_year=fiscal_year,
            period_type=period_type,
            fiscal_quarter=fiscal_quarter,
            accounting_standard=accounting_standard,
            consolidated=consolidated,
            force=force,
            pdf_label=filename,
        )
    except ReportAlreadyExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except LLMNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except LLMParseError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"LLM вернул некорректный JSON: {exc}",
        ) from exc
    except LLMTransientError as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=f"LLM временно недоступен: {exc}",
        ) from exc
    except RuntimeError as exc:
        # extract_financial_pages бросает RuntimeError если в PDF ничего не нашлось
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.exception("Ошибка парсинга PDF для company_id=%s: %s", company_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Не удалось обработать PDF: {exc}",
        ) from exc

    if not outcome.created_report_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Пайплайн завершился без созданного отчёта (внутренняя ошибка).",
        )

    created = report_service.get_report_by_id(db, outcome.created_report_id)
    if not created:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Отчёт создан, но не найден при повторном чтении из БД.",
        )

    # Мини-анализ неполных полей — отдадим фронту для подсветки
    warnings: List[str] = []
    ex = outcome.extracted
    if ex:
        if ex.net_income is None:
            warnings.append("net_income не найден — проверьте вручную")
        if ex.equity is None:
            warnings.append("equity не найден — проверьте вручную")
        if outcome.report_type == "bank" and ex.revenue is None:
            warnings.append("revenue (Total Operating Income) не найден — обязательно проверьте")
        if outcome.report_type != "bank" and (
            ex.current_assets is None or ex.current_liabilities is None
        ):
            warnings.append("current_assets/current_liabilities не найдены")

    return ParsePdfResponse(
        report=FinancialReport.model_validate(created, from_attributes=True),
        auto_extracted=True,
        extraction_model=settings.extraction_model_label,
        selected_pages=outcome.selected_pages,
        total_pages=outcome.total_pages,
        warnings=warnings,
    )


# ─── Сравнение AI-извлечения с уже существующим отчётом ─────────────────────


class ReportFieldDiffOut(BaseModel):
    """Diff по одному полю — как представлен в ответе API."""
    field: str
    label: str
    kind: str  # money_mln | int | float | bool | str | date
    existing_value: Optional[object] = None
    extracted_value: Optional[object] = None
    abs_diff: Optional[float] = None
    pct_diff: Optional[float] = None
    status: str  # match | close | mismatch | missing_ai | missing_existing | both_missing
    note: Optional[str] = None


class ComparisonSummaryOut(BaseModel):
    total_fields: int
    matched: int
    close: int
    mismatched: int
    missing_in_ai: int
    missing_in_existing: int
    both_missing: int
    max_pct_diff: Optional[float] = None


class ComparePdfResponse(BaseModel):
    ticker: str
    fiscal_year: int
    report_type: str
    existing_report_id: int
    existing_report_verified: bool
    extraction_model: str
    selected_pages: int
    total_pages: int
    diffs: List[ReportFieldDiffOut]
    summary: ComparisonSummaryOut
    extracted: dict  # ExtractedReport.model_dump() — "как увидела модель"


@router.post("/compare-pdf", response_model=ComparePdfResponse)
async def compare_pdf_endpoint(
    company_id: int = Form(..., description="ID компании"),
    fiscal_year: int = Form(..., description="Отчётный год"),
    period_type: str = Form("annual"),
    fiscal_quarter: Optional[int] = Form(None),
    accounting_standard: str = Form("IFRS"),
    consolidated: bool = Form(True),
    file: UploadFile = File(..., description="PDF-файл отчёта"),
    db: Session = Depends(get_db),
):
    """
    Прогнать PDF через AI-парсер и СРАВНИТЬ с уже существующим (проверенным)
    отчётом в БД. Ничего не пишется и не перезаписывается — только diff.

    Возвращает массив `diffs` по всем полям со статусами:
    - `match` — значения совпали (с учётом округлений);
    - `close` — отличаются < 1% (обычно допустимо);
    - `mismatch` — значимое расхождение, нужно внимание;
    - `missing_ai` — аналитик ввёл, модель не нашла;
    - `missing_existing` — модель нашла, аналитик не ввёл;
    - `both_missing` — оба пусты.
    """
    if not settings.llm_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LLM не сконфигурирован. Задайте LLM_API_KEY в .env.",
        )

    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Компания с ID {company_id} не найдена",
        )

    filename = file.filename or "uploaded.pdf"
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ожидается файл с расширением .pdf",
        )
    pdf_bytes = await file.read()
    if not pdf_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Передан пустой файл",
        )

    try:
        result = compare_pdf_with_existing(
            db=db,
            pdf_source=pdf_bytes,
            company=company,
            fiscal_year=fiscal_year,
            period_type=period_type,
            fiscal_quarter=fiscal_quarter,
            accounting_standard=accounting_standard,
            consolidated=consolidated,
            pdf_label=filename,
        )
    except ReportNotFoundForComparison as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except LLMNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except LLMParseError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"LLM вернул некорректный JSON: {exc}",
        ) from exc
    except LLMTransientError as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=f"LLM временно недоступен: {exc}",
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.exception("Ошибка compare-pdf для company_id=%s: %s", company_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Не удалось сравнить PDF: {exc}",
        ) from exc

    diffs_out = [
        ReportFieldDiffOut(
            field=d.field,
            label=d.label,
            kind=d.kind,
            existing_value=_normalize_for_json(d.existing_value),
            extracted_value=_normalize_for_json(d.extracted_value),
            abs_diff=d.abs_diff,
            pct_diff=d.pct_diff,
            status=d.status,
            note=d.note,
        )
        for d in result.diffs
    ]

    return ComparePdfResponse(
        ticker=result.ticker,
        fiscal_year=result.fiscal_year,
        report_type=result.report_type,
        existing_report_id=result.existing_report_id,
        existing_report_verified=result.existing_report_verified,
        extraction_model=settings.extraction_model_label,
        selected_pages=result.selected_pages,
        total_pages=result.total_pages,
        diffs=diffs_out,
        summary=ComparisonSummaryOut(
            total_fields=result.summary.total_fields,
            matched=result.summary.matched,
            close=result.summary.close,
            mismatched=result.summary.mismatched,
            missing_in_ai=result.summary.missing_in_ai,
            missing_in_existing=result.summary.missing_in_existing,
            both_missing=result.summary.both_missing,
            max_pct_diff=result.summary.max_pct_diff,
        ),
        extracted=result.extracted.model_dump(mode="json"),
    )


def _normalize_for_json(value):
    """Преобразует даты/Decimal в примитивы для JSON-ответа."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float, str)):
        return value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    # decimal.Decimal и прочее — приводим к float, если не получается — str
    try:
        return float(value)
    except (TypeError, ValueError):
        return str(value)
