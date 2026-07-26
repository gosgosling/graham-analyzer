"""Фоновый воркер массового парсинга (один поток на процесс)."""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.database import SessionLocal
from app.models.company import Company
from app.models.mass_parse import MassParseItem, MassParseJob
from app.services.report_parser.extractor_service import (
    ReportAlreadyExistsError,
    parse_pdf_to_report,
)
from app.services.report_parser.llm_client import (
    LLMQuotaExhaustedError,
    LLMRateLimitError,
    LLMTransientError,
)

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_thread: Optional[threading.Thread] = None
_active_job_id: Optional[int] = None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def is_worker_alive(job_id: Optional[int] = None) -> bool:
    with _lock:
        alive = _thread is not None and _thread.is_alive()
        if job_id is None:
            return alive
        return alive and _active_job_id == job_id


def recover_orphaned_running_jobs() -> int:
    """При старте API: running без живого воркера → paused (можно продолжить)."""
    db = SessionLocal()
    try:
        jobs = db.query(MassParseJob).filter(MassParseJob.status == "running").all()
        n = 0
        for job in jobs:
            if is_worker_alive(job.id):
                continue
            job.status = "paused"
            job.last_message = "Прервано перезапуском сервера — можно продолжить (Resume)."
            job.updated_at = _utcnow()
            stuck = (
                db.query(MassParseItem)
                .filter(MassParseItem.job_id == job.id)
                .filter(MassParseItem.status == "running")
                .all()
            )
            for item in stuck:
                item.status = "pending"
                item.message = "Сброшено после перезапуска сервера"
                item.started_at = None
            n += 1
        if n:
            db.commit()
            logger.warning("Mass-parse: %s orphaned running job(s) → paused", n)
        return n
    finally:
        db.close()


def start_worker(job_id: int) -> bool:
    """Запустить поток для job_id. False если уже крутится другой/этот job."""
    global _thread, _active_job_id
    with _lock:
        if _thread is not None and _thread.is_alive():
            if _active_job_id == job_id:
                return True
            return False
        _active_job_id = job_id
        _thread = threading.Thread(
            target=_run_job_loop,
            args=(job_id,),
            name=f"mass-parse-{job_id}",
            daemon=True,
        )
        _thread.start()
        return True


def _run_job_loop(job_id: int) -> None:
    global _active_job_id
    logger.info("Mass-parse worker started for job_id=%s", job_id)
    try:
        while True:
            db = SessionLocal()
            try:
                job = db.query(MassParseJob).filter(MassParseJob.id == job_id).first()
                if not job:
                    logger.error("Mass-parse job %s not found", job_id)
                    return

                if job.status in ("paused", "cancelled", "completed"):
                    logger.info("Mass-parse job %s stopped with status=%s", job_id, job.status)
                    return

                if job.status != "running":
                    # pending без явного start — не трогаем
                    return

                item = (
                    db.query(MassParseItem)
                    .filter(MassParseItem.job_id == job_id)
                    .filter(MassParseItem.status == "pending")
                    .order_by(MassParseItem.position.asc())
                    .first()
                )
                if item is None:
                    job.status = "completed"
                    job.finished_at = _utcnow()
                    job.updated_at = _utcnow()
                    job.current_item_id = None
                    job.last_message = (
                        f"Готово: ok={job.done_ok}, skipped={job.done_skipped}, "
                        f"error={job.done_error}"
                    )
                    db.commit()
                    logger.info("Mass-parse job %s completed", job_id)
                    return

                item_id = int(item.id)
                # Отпускаем сессию перед долгим LLM-вызовом — берём свежую внутри
                db.commit()
            finally:
                db.close()

            _process_one_item(job_id, item_id)

            # После item ещё раз проверяем pause/cancel (флаги выставляет API)
            db = SessionLocal()
            try:
                job = db.query(MassParseJob).filter(MassParseJob.id == job_id).first()
                if not job or job.status != "running":
                    return
            finally:
                db.close()
    except Exception:
        logger.exception("Mass-parse worker crashed for job_id=%s", job_id)
        db = SessionLocal()
        try:
            job = db.query(MassParseJob).filter(MassParseJob.id == job_id).first()
            if job and job.status == "running":
                job.status = "paused"
                job.last_message = "Воркер упал с необработанной ошибкой — статус paused, можно Resume."
                job.updated_at = _utcnow()
                db.commit()
        finally:
            db.close()
    finally:
        with _lock:
            if _active_job_id == job_id:
                _active_job_id = None
        logger.info("Mass-parse worker finished for job_id=%s", job_id)


def _process_one_item(job_id: int, item_id: int) -> None:
    db = SessionLocal()
    try:
        job = db.query(MassParseJob).filter(MassParseJob.id == job_id).first()
        item = db.query(MassParseItem).filter(MassParseItem.id == item_id).first()
        if not job or not item or job.status != "running":
            return
        if item.status != "pending":
            return

        item.status = "running"
        item.started_at = _utcnow()
        item.message = None
        job.current_item_id = item.id
        job.last_message = f"Парсинг {item.ticker} {item.fiscal_year}…"
        job.updated_at = _utcnow()
        db.commit()

        # Снимок полей до LLM
        ticker = item.ticker
        fiscal_year = item.fiscal_year
        pdf_path = Path(item.pdf_path)
        company_id = item.company_id
        force = bool(job.force)
        accounting_standard = job.accounting_standard
        consolidated = bool(job.consolidated)

        if company_id is None or fiscal_year is None:
            _finish_item(
                db,
                job,
                item,
                status="skipped",
                message="Нет company_id или fiscal_year",
            )
            return

        if not pdf_path.is_file():
            _finish_item(
                db,
                job,
                item,
                status="error",
                message=f"Файл не найден: {pdf_path}",
            )
            return

        company = db.query(Company).filter(Company.id == company_id).first()
        if not company:
            _finish_item(
                db,
                job,
                item,
                status="error",
                message=f"Компания id={company_id} не найдена",
            )
            return

        # Rate-limit: несколько попыток, затем error и дальше по очереди
        last_err: Optional[BaseException] = None
        for attempt in range(1, 4):
            try:
                outcome = parse_pdf_to_report(
                    db=db,
                    pdf_source=pdf_path,
                    company=company,
                    fiscal_year=int(fiscal_year),
                    force=force,
                    period_type="annual",
                    accounting_standard=accounting_standard,
                    consolidated=consolidated,
                    source_pdf_path=str(pdf_path),
                    pdf_label=pdf_path.name,
                )
                _finish_item(
                    db,
                    job,
                    item,
                    status="success",
                    message=f"report_id={outcome.created_report_id}",
                    report_id=outcome.created_report_id,
                )
                return
            except ReportAlreadyExistsError as exc:
                _finish_item(
                    db,
                    job,
                    item,
                    status="skipped",
                    message=str(exc) or "Отчёт уже существует",
                )
                return
            except LLMQuotaExhaustedError as exc:
                # Квота free tier / AllocationQuota — не долбим ретраями, ставим паузу.
                _finish_item(
                    db,
                    job,
                    item,
                    status="error",
                    message=f"Квота LLM исчерпана: {exc}"[:2000],
                )
                job = db.query(MassParseJob).filter(MassParseJob.id == job_id).first()
                if job and job.status == "running":
                    job.status = "paused"
                    job.last_message = (
                        "Пауза: FreeTierOnly / квота модели. "
                        "Смени LLM_MODEL или открой pay-as-you-go, затем Resume."
                    )
                    job.updated_at = _utcnow()
                    db.commit()
                return
            except LLMRateLimitError as exc:
                last_err = exc
                wait_s = max(5.0, float(getattr(exc, "retry_after", 30) or 30))
                logger.warning(
                    "Mass-parse rate limit %s %s attempt=%s wait=%.0fs",
                    ticker,
                    fiscal_year,
                    attempt,
                    wait_s,
                )
                item.message = f"Rate limit, жду {wait_s:.0f}с (попытка {attempt}/3)"
                job.last_message = item.message
                job.updated_at = _utcnow()
                db.commit()
                # Не держим транзакцию на sleep
                db.commit()
                time.sleep(wait_s)
                # Проверяем pause
                db.refresh(job)
                if job.status != "running":
                    item.status = "pending"
                    item.started_at = None
                    item.message = "Остановлено во время ожидания rate limit"
                    db.commit()
                    return
            except LLMTransientError as exc:
                last_err = exc
                logger.warning(
                    "Mass-parse transient %s %s attempt=%s: %s",
                    ticker,
                    fiscal_year,
                    attempt,
                    exc,
                )
                item.message = f"Временная ошибка LLM, retry {attempt}/3: {exc}"
                job.last_message = item.message
                job.updated_at = _utcnow()
                db.commit()
                time.sleep(min(30.0 * attempt, 90.0))
                db.refresh(job)
                if job.status != "running":
                    item.status = "pending"
                    item.started_at = None
                    item.message = "Остановлено во время retry"
                    db.commit()
                    return
            except Exception as exc:  # noqa: BLE001 — item error не роняет job
                db.rollback()
                # После rollback перечитываем
                job = db.query(MassParseJob).filter(MassParseJob.id == job_id).first()
                item = db.query(MassParseItem).filter(MassParseItem.id == item_id).first()
                if not job or not item:
                    return
                logger.exception(
                    "Mass-parse item error job=%s %s %s: %s",
                    job_id,
                    ticker,
                    fiscal_year,
                    exc,
                )
                _finish_item(
                    db,
                    job,
                    item,
                    status="error",
                    message=str(exc)[:2000],
                )
                return

        # Исчерпали retry
        db.rollback()
        job = db.query(MassParseJob).filter(MassParseJob.id == job_id).first()
        item = db.query(MassParseItem).filter(MassParseItem.id == item_id).first()
        if job and item:
            _finish_item(
                db,
                job,
                item,
                status="error",
                message=f"После 3 попыток: {last_err}",
            )
    finally:
        db.close()


def _finish_item(
    db,
    job: MassParseJob,
    item: MassParseItem,
    *,
    status: str,
    message: str,
    report_id: Optional[int] = None,
) -> None:
    item.status = status
    item.message = message
    item.report_id = report_id
    item.finished_at = _utcnow()
    if status == "success":
        job.done_ok = int(job.done_ok or 0) + 1
    elif status == "skipped":
        job.done_skipped = int(job.done_skipped or 0) + 1
    elif status == "error":
        job.done_error = int(job.done_error or 0) + 1
    job.current_item_id = None
    job.last_message = f"{item.ticker} {item.fiscal_year}: {status} — {message[:200]}"
    job.updated_at = _utcnow()
    db.commit()
