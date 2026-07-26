"""Очередь точечного парсинга PDF (конкретные периоды, без skip тикера)."""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.company import Company
from app.models.disclosure import DisclosureParseItem, DisclosureParseJob, DisclosurePeriod
from app.services.disclosure.edisclosure_client import download_company_reports
from app.services.disclosure.paths import pdf_path_for
from app.services.disclosure.sync_service import refresh_flags_only
from app.services.report_parser.extractor_service import (
    ReportAlreadyExistsError,
    parse_pdf_to_report,
)
from app.services.report_parser.llm_client import LLMQuotaExhaustedError

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_thread: Optional[threading.Thread] = None
_active_job_id: Optional[int] = None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def is_parse_worker_alive(job_id: Optional[int] = None) -> bool:
    with _lock:
        alive = _thread is not None and _thread.is_alive()
        if job_id is None:
            return alive
        return alive and _active_job_id == job_id


def download_periods(db: Session, period_ids: list[int]) -> dict:
    """Скачать выбранные disclosure_periods на диск."""
    rows = (
        db.query(DisclosurePeriod)
        .filter(DisclosurePeriod.id.in_(period_ids))
        .all()
    )
    by_ticker: dict[str, list] = {}
    for row in rows:
        if not row.file_url:
            continue
        by_ticker.setdefault(row.ticker, []).append(
            {
                "doc_type": row.doc_type or "",
                "period": row.period_label or row.period_key,
                "fiscal_year": row.fiscal_year,
                "period_type": row.period_type,
                "fiscal_quarter": row.fiscal_quarter,
                "period_key": row.period_key,
                "interim_rank": 0,
                "file_url": row.file_url,
                "file_label": "zip",
                "published_at": row.published_at,
            }
        )

    downloaded: dict[str, str] = {}
    errors: list[str] = []
    for ticker, reports in by_ticker.items():
        try:
            result = download_company_reports(ticker, reports)
            downloaded.update({f"{ticker}:{k}": v for k, v in result.items()})
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{ticker}: {exc}")

    # обновить on_disk
    for row in rows:
        path = pdf_path_for(
            row.ticker, row.period_type, row.fiscal_year, row.fiscal_quarter
        )
        if path.is_file():
            row.on_disk = True
            row.pdf_path = str(path)
    db.commit()
    refresh_flags_only(db)
    return {"downloaded": len(downloaded), "paths": downloaded, "errors": errors}


def enqueue_parse(db: Session, period_ids: list[int], *, auto_start: bool = True) -> DisclosureParseJob:
    rows = (
        db.query(DisclosurePeriod)
        .filter(DisclosurePeriod.id.in_(period_ids))
        .all()
    )
    if not rows:
        raise ValueError("Периоды не найдены")

    now = _utcnow()
    job = DisclosureParseJob(
        status="pending",
        total_items=0,
        created_at=now,
        updated_at=now,
        last_message="Создание очереди…",
    )
    db.add(job)
    db.flush()

    pos = 0
    for row in rows:
        path = row.pdf_path or str(
            pdf_path_for(row.ticker, row.period_type, row.fiscal_year, row.fiscal_quarter)
        )
        if not Path(path).is_file():
            # пропустим в очередь с ошибкой сразу? лучше skip при создании
            db.add(
                DisclosureParseItem(
                    job_id=job.id,
                    position=pos,
                    disclosure_period_id=row.id,
                    company_id=row.company_id,
                    ticker=row.ticker,
                    fiscal_year=row.fiscal_year,
                    period_type=row.period_type,
                    fiscal_quarter=row.fiscal_quarter,
                    pdf_path=path,
                    status="error",
                    message="PDF нет на диске — сначала Скачать",
                    finished_at=now,
                )
            )
            job.done_error += 1
            pos += 1
            continue
        db.add(
            DisclosureParseItem(
                job_id=job.id,
                position=pos,
                disclosure_period_id=row.id,
                company_id=row.company_id,
                ticker=row.ticker,
                fiscal_year=row.fiscal_year,
                period_type=row.period_type,
                fiscal_quarter=row.fiscal_quarter,
                pdf_path=path,
                status="pending",
            )
        )
        pos += 1

    job.total_items = pos
    job.last_message = f"В очереди {pos} файлов"
    db.commit()
    db.refresh(job)

    if auto_start and job.done_error < job.total_items:
        start_parse_job(db, job.id)
        db.refresh(job)
    return job


def start_parse_job(db: Session, job_id: int) -> DisclosureParseJob:
    global _thread, _active_job_id
    job = db.query(DisclosureParseJob).filter(DisclosureParseJob.id == job_id).first()
    if not job:
        raise LookupError(f"Job {job_id} не найден")
    with _lock:
        if _thread is not None and _thread.is_alive():
            if _active_job_id == job_id:
                return job
            raise RuntimeError("Уже выполняется другой parse job")
        job.status = "running"
        if job.started_at is None:
            job.started_at = _utcnow()
        job.updated_at = _utcnow()
        db.commit()
        _active_job_id = job_id
        _thread = threading.Thread(
            target=_parse_loop,
            args=(job_id,),
            name=f"disclosure-parse-{job_id}",
            daemon=True,
        )
        _thread.start()
    db.refresh(job)
    return job


def _parse_loop(job_id: int) -> None:
    global _active_job_id
    try:
        while True:
            db = SessionLocal()
            try:
                job = db.query(DisclosureParseJob).filter(DisclosureParseJob.id == job_id).first()
                if not job or job.status != "running":
                    return
                item = (
                    db.query(DisclosureParseItem)
                    .filter(DisclosureParseItem.job_id == job_id)
                    .filter(DisclosureParseItem.status == "pending")
                    .order_by(DisclosureParseItem.position.asc())
                    .first()
                )
                if item is None:
                    job.status = "completed"
                    job.finished_at = _utcnow()
                    job.last_message = (
                        f"Готово: ok={job.done_ok}, err={job.done_error}, "
                        f"skip={job.done_skipped}"
                    )
                    job.updated_at = _utcnow()
                    db.commit()
                    refresh_flags_only(db)
                    return
                item_id = int(item.id)
                db.commit()
            finally:
                db.close()

            _process_item(job_id, item_id)
    finally:
        with _lock:
            if _active_job_id == job_id:
                _active_job_id = None


def _process_item(job_id: int, item_id: int) -> None:
    db = SessionLocal()
    try:
        job = db.query(DisclosureParseJob).filter(DisclosureParseJob.id == job_id).first()
        item = db.query(DisclosureParseItem).filter(DisclosureParseItem.id == item_id).first()
        if not job or not item or job.status != "running":
            return
        item.status = "running"
        item.started_at = _utcnow()
        job.last_message = f"Парсинг {item.ticker} {item.period_type} {item.fiscal_year}"
        job.updated_at = _utcnow()
        db.commit()

        company = db.query(Company).filter(Company.id == item.company_id).first()
        path = Path(item.pdf_path)
        if not company or not path.is_file():
            item.status = "error"
            item.message = "Нет компании или PDF"
            item.finished_at = _utcnow()
            job.done_error += 1
            db.commit()
            return

        try:
            outcome = parse_pdf_to_report(
                db=db,
                pdf_source=path,
                company=company,
                fiscal_year=int(item.fiscal_year),
                period_type=item.period_type,
                fiscal_quarter=item.fiscal_quarter,
                force=False,
                source_pdf_path=str(path),
                pdf_label=path.name,
            )
            item.status = "success"
            item.report_id = outcome.created_report_id
            item.message = f"report_id={outcome.created_report_id}"
            item.finished_at = _utcnow()
            job.done_ok += 1
            if item.disclosure_period_id:
                dp = (
                    db.query(DisclosurePeriod)
                    .filter(DisclosurePeriod.id == item.disclosure_period_id)
                    .first()
                )
                if dp:
                    dp.in_db = True
                    dp.report_id = outcome.created_report_id
                    dp.coverage_status = "in_service"
            db.commit()
        except ReportAlreadyExistsError as exc:
            item.status = "skipped"
            item.message = str(exc)
            item.finished_at = _utcnow()
            job.done_skipped += 1
            db.commit()
        except LLMQuotaExhaustedError as exc:
            item.status = "error"
            item.message = f"Квота LLM: {exc}"[:2000]
            item.finished_at = _utcnow()
            job.done_error += 1
            job.status = "paused"
            job.last_message = "Пауза: FreeTierOnly / квота"
            job.updated_at = _utcnow()
            db.commit()
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            job = db.query(DisclosureParseJob).filter(DisclosureParseJob.id == job_id).first()
            item = db.query(DisclosureParseItem).filter(DisclosureParseItem.id == item_id).first()
            if job and item:
                item.status = "error"
                item.message = str(exc)[:2000]
                item.finished_at = _utcnow()
                job.done_error += 1
                job.updated_at = _utcnow()
                db.commit()
            logger.exception("Disclosure parse item %s failed", item_id)
    finally:
        db.close()
