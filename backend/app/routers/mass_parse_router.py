"""API массового AI-парсинга PDF с диска."""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.mass_parse import MassParseJob
from app.services.mass_parse import service as mass_parse_service
from app.services.mass_parse.worker import is_worker_alive

router = APIRouter(prefix="/mass-parse", tags=["mass-parse"])


class MassParsePreviewOut(BaseModel):
    reports_root: str
    ticker_dirs: int
    pdf_files: int
    queued: int
    skipped_company_has_reports: int
    skipped_company_not_found: int
    skipped_no_year: int
    skipped_banks: int
    companies_with_reports_in_db: int
    llm_configured: bool
    llm_model: str


class MassParseCreateIn(BaseModel):
    reports_root: Optional[str] = Field(
        None, description="Корень с папками-тикерами; по умолчанию из .env"
    )
    skip_companies_with_reports: bool = True
    skip_banks: bool = True
    force: bool = False
    accounting_standard: str = "IFRS"
    consolidated: bool = True
    auto_start: bool = True


class MassParseItemOut(BaseModel):
    id: int
    position: int
    ticker: str
    company_id: Optional[int] = None
    fiscal_year: Optional[int] = None
    pdf_path: str
    status: str
    message: Optional[str] = None
    report_id: Optional[int] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class MassParseJobOut(BaseModel):
    id: int
    status: str
    reports_root: str
    skip_companies_with_reports: bool
    force: bool
    accounting_standard: str
    consolidated: bool
    total_items: int
    done_ok: int
    done_skipped: int
    done_error: int
    pending_count: int = 0
    processed_count: int = 0
    current_item_id: Optional[int] = None
    last_message: Optional[str] = None
    worker_alive: bool = False
    created_at: datetime
    updated_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


def _job_out(job: MassParseJob) -> MassParseJobOut:
    processed = int(job.done_ok or 0) + int(job.done_skipped or 0) + int(job.done_error or 0)
    pending = max(0, int(job.total_items or 0) - processed)
    # running item ещё не в счётчиках
    if job.status == "running" and job.current_item_id:
        pending = max(0, pending - 1)
    return MassParseJobOut(
        id=job.id,
        status=job.status,
        reports_root=job.reports_root,
        skip_companies_with_reports=job.skip_companies_with_reports,
        force=job.force,
        accounting_standard=job.accounting_standard,
        consolidated=job.consolidated,
        total_items=job.total_items,
        done_ok=job.done_ok,
        done_skipped=job.done_skipped,
        done_error=job.done_error,
        pending_count=pending,
        processed_count=processed,
        current_item_id=job.current_item_id,
        last_message=job.last_message,
        worker_alive=is_worker_alive(job.id),
        created_at=job.created_at,
        updated_at=job.updated_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


@router.get("/preview", response_model=MassParsePreviewOut)
def preview(
    reports_root: Optional[str] = Query(None),
    skip_companies_with_reports: bool = Query(True),
    skip_banks: bool = Query(True),
    db: Session = Depends(get_db),
):
    try:
        scan = mass_parse_service.preview_scan(
            db,
            reports_root=reports_root,
            skip_companies_with_reports=skip_companies_with_reports,
            skip_banks=skip_banks,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return MassParsePreviewOut(
        reports_root=scan.reports_root,
        ticker_dirs=scan.ticker_dirs,
        pdf_files=scan.pdf_files,
        queued=scan.queued,
        skipped_company_has_reports=scan.skipped_company_has_reports,
        skipped_company_not_found=scan.skipped_company_not_found,
        skipped_no_year=scan.skipped_no_year,
        skipped_banks=scan.skipped_banks,
        companies_with_reports_in_db=scan.companies_with_reports_in_db,
        llm_configured=settings.llm_configured,
        llm_model=settings.extraction_model_label if settings.llm_configured else "",
    )


@router.get("/jobs", response_model=List[MassParseJobOut])
def list_jobs(db: Session = Depends(get_db)):
    return [_job_out(j) for j in mass_parse_service.list_jobs(db)]


@router.post("/jobs", response_model=MassParseJobOut, status_code=status.HTTP_201_CREATED)
def create_job(body: MassParseCreateIn, db: Session = Depends(get_db)):
    if not settings.llm_configured:
        raise HTTPException(
            status_code=503,
            detail="LLM не сконфигурирован — задайте LLM_API_KEY / LLM_MODEL в .env",
        )
    try:
        job = mass_parse_service.create_job(
            db,
            reports_root=body.reports_root,
            skip_companies_with_reports=body.skip_companies_with_reports,
            skip_banks=body.skip_banks,
            force=body.force,
            accounting_standard=body.accounting_standard,
            consolidated=body.consolidated,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if body.auto_start:
        try:
            job = mass_parse_service.start_job(db, job.id)
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _job_out(job)


@router.get("/jobs/{job_id}", response_model=MassParseJobOut)
def get_job(job_id: int, db: Session = Depends(get_db)):
    job = mass_parse_service.get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job не найден")
    return _job_out(job)


@router.get("/jobs/{job_id}/items", response_model=List[MassParseItemOut])
def get_items(
    job_id: int,
    status_filter: Optional[str] = Query(None, alias="status"),
    limit: int = Query(200, ge=1, le=2000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    if not mass_parse_service.get_job(db, job_id):
        raise HTTPException(status_code=404, detail="Job не найден")
    return mass_parse_service.list_items(
        db, job_id, status=status_filter, limit=limit, offset=offset
    )


@router.post("/jobs/{job_id}/start", response_model=MassParseJobOut)
def start(job_id: int, db: Session = Depends(get_db)):
    try:
        return _job_out(mass_parse_service.start_job(db, job_id))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/jobs/{job_id}/pause", response_model=MassParseJobOut)
def pause(job_id: int, db: Session = Depends(get_db)):
    try:
        return _job_out(mass_parse_service.pause_job(db, job_id))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/jobs/{job_id}/resume", response_model=MassParseJobOut)
def resume(job_id: int, db: Session = Depends(get_db)):
    try:
        return _job_out(mass_parse_service.resume_job(db, job_id))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/jobs/{job_id}/cancel", response_model=MassParseJobOut)
def cancel(job_id: int, db: Session = Depends(get_db)):
    try:
        return _job_out(mass_parse_service.cancel_job(db, job_id))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/jobs/{job_id}/retry-errors", response_model=MassParseJobOut)
def retry_errors(job_id: int, db: Session = Depends(get_db)):
    try:
        return _job_out(mass_parse_service.retry_errors(db, job_id))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/jobs/{job_id}/drop-banks", response_model=MassParseJobOut)
def drop_banks(job_id: int, db: Session = Depends(get_db)):
    """Убрать из очереди pending bank/financial PDF (Грэм — отдельно)."""
    try:
        job, _n = mass_parse_service.drop_banks_from_job(db, job_id)
        return _job_out(job)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
