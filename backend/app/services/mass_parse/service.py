"""CRUD и управление заданиями массового парсинга."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.models.company import Company
from app.models.enums import sector_to_report_type
from app.models.mass_parse import MassParseItem, MassParseJob
from app.services.mass_parse.scanner import ScanPreview, scan_reports_dir
from app.services.mass_parse.worker import is_worker_alive, start_worker


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def default_reports_root() -> Path:
    return Path(settings.MASS_PARSE_REPORTS_DIR).expanduser()


def preview_scan(
    db: Session,
    *,
    reports_root: Optional[str] = None,
    skip_companies_with_reports: bool = True,
    skip_banks: bool = True,
) -> ScanPreview:
    root = Path(reports_root) if reports_root else default_reports_root()
    return scan_reports_dir(
        db,
        root,
        skip_companies_with_reports=skip_companies_with_reports,
        skip_banks=skip_banks,
        include_skipped_in_items=False,
    )


def create_job(
    db: Session,
    *,
    reports_root: Optional[str] = None,
    skip_companies_with_reports: bool = True,
    skip_banks: bool = True,
    force: bool = False,
    accounting_standard: str = "IFRS",
    consolidated: bool = True,
) -> MassParseJob:
    preview = preview_scan(
        db,
        reports_root=reports_root,
        skip_companies_with_reports=skip_companies_with_reports,
        skip_banks=skip_banks,
    )
    if preview.queued == 0:
        raise ValueError(
            "Нет PDF для постановки в очередь. "
            f"Корень: {preview.reports_root}. "
            f"Пропущено (уже есть отчёты): {preview.skipped_company_has_reports}, "
            f"банки: {preview.skipped_banks}, "
            f"нет компании: {preview.skipped_company_not_found}, "
            f"без года: {preview.skipped_no_year}."
        )

    now = _utcnow()
    job = MassParseJob(
        status="pending",
        reports_root=preview.reports_root,
        skip_companies_with_reports=skip_companies_with_reports,
        force=force,
        accounting_standard=accounting_standard,
        consolidated=consolidated,
        total_items=preview.queued,
        done_ok=0,
        done_skipped=0,
        done_error=0,
        last_message=(
            f"Создано: {preview.queued} PDF в очереди "
            f"(тикеров с отчётами в БД: {preview.companies_with_reports_in_db})"
        ),
        created_at=now,
        updated_at=now,
    )
    db.add(job)
    db.flush()

    for pos, scanned in enumerate(preview.items):
        if scanned.skip_reason:
            continue
        db.add(
            MassParseItem(
                job_id=job.id,
                position=pos,
                ticker=scanned.ticker,
                company_id=scanned.company_id,
                fiscal_year=scanned.fiscal_year,
                pdf_path=scanned.pdf_path,
                status="pending",
            )
        )
    db.commit()
    db.refresh(job)
    return job


def get_job(db: Session, job_id: int) -> Optional[MassParseJob]:
    return db.query(MassParseJob).filter(MassParseJob.id == job_id).first()


def list_jobs(db: Session, limit: int = 20) -> list[MassParseJob]:
    return (
        db.query(MassParseJob)
        .order_by(MassParseJob.id.desc())
        .limit(limit)
        .all()
    )


def list_items(
    db: Session,
    job_id: int,
    *,
    status: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
) -> list[MassParseItem]:
    q = db.query(MassParseItem).filter(MassParseItem.job_id == job_id)
    if status:
        q = q.filter(MassParseItem.status == status)
    return (
        q.order_by(MassParseItem.position.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )


def recount_job_stats(db: Session, job: MassParseJob) -> None:
    items = db.query(MassParseItem).filter(MassParseItem.job_id == job.id).all()
    job.done_ok = sum(1 for i in items if i.status == "success")
    job.done_skipped = sum(1 for i in items if i.status == "skipped")
    job.done_error = sum(1 for i in items if i.status == "error")
    job.total_items = len(items)


def start_job(db: Session, job_id: int) -> MassParseJob:
    job = get_job(db, job_id)
    if not job:
        raise LookupError(f"Job {job_id} не найден")
    if job.status in ("completed", "cancelled"):
        raise ValueError(f"Job в статусе {job.status} нельзя запустить")
    if job.status == "running" and is_worker_alive(job_id):
        return job

    # Другой job уже крутится?
    other = (
        db.query(MassParseJob)
        .filter(MassParseJob.status == "running")
        .filter(MassParseJob.id != job_id)
        .first()
    )
    if other and is_worker_alive(other.id):
        raise ValueError(f"Уже выполняется job #{other.id}. Сначала Pause/Cancel.")

    job.status = "running"
    if job.started_at is None:
        job.started_at = _utcnow()
    job.finished_at = None
    job.last_message = "Запуск…"
    job.updated_at = _utcnow()
    db.commit()
    db.refresh(job)

    if not start_worker(job_id):
        job.status = "paused"
        job.last_message = "Не удалось запустить воркер (занят другим заданием)."
        job.updated_at = _utcnow()
        db.commit()
        db.refresh(job)
        raise RuntimeError(job.last_message)
    return job


def pause_job(db: Session, job_id: int) -> MassParseJob:
    """Мягкая пауза: текущий PDF допарсится, следующий не начнётся."""
    job = get_job(db, job_id)
    if not job:
        raise LookupError(f"Job {job_id} не найден")
    if job.status != "running":
        raise ValueError(f"Пауза доступна только для running (сейчас {job.status})")
    job.status = "paused"
    job.last_message = "Пауза запрошена — после текущего PDF остановимся."
    job.updated_at = _utcnow()
    db.commit()
    db.refresh(job)
    return job


def resume_job(db: Session, job_id: int) -> MassParseJob:
    job = get_job(db, job_id)
    if not job:
        raise LookupError(f"Job {job_id} не найден")
    if job.status not in ("paused", "pending"):
        raise ValueError(f"Resume только для paused/pending (сейчас {job.status})")
    # Сбросить зависшие running → pending
    stuck = (
        db.query(MassParseItem)
        .filter(MassParseItem.job_id == job_id)
        .filter(MassParseItem.status == "running")
        .all()
    )
    for item in stuck:
        item.status = "pending"
        item.started_at = None
        item.message = "Сброшено перед resume"
    db.commit()
    return start_job(db, job_id)


def cancel_job(db: Session, job_id: int) -> MassParseJob:
    job = get_job(db, job_id)
    if not job:
        raise LookupError(f"Job {job_id} не найден")
    if job.status in ("completed", "cancelled"):
        return job
    job.status = "cancelled"
    job.finished_at = _utcnow()
    job.last_message = "Отменено пользователем"
    job.updated_at = _utcnow()
    pending = (
        db.query(MassParseItem)
        .filter(MassParseItem.job_id == job_id)
        .filter(MassParseItem.status == "pending")
        .all()
    )
    for item in pending:
        item.status = "cancelled"
        item.finished_at = _utcnow()
        item.message = "Отменено"
    recount_job_stats(db, job)
    db.commit()
    db.refresh(job)
    return job


def retry_errors(db: Session, job_id: int) -> MassParseJob:
    """Вернуть error-элементы в pending (для повторного прогона после фикса)."""
    job = get_job(db, job_id)
    if not job:
        raise LookupError(f"Job {job_id} не найден")
    if job.status == "running" and is_worker_alive(job_id):
        raise ValueError("Сначала поставьте job на паузу")
    errors = (
        db.query(MassParseItem)
        .filter(MassParseItem.job_id == job_id)
        .filter(MassParseItem.status == "error")
        .all()
    )
    for item in errors:
        item.status = "pending"
        item.message = "Повтор после ошибки"
        item.started_at = None
        item.finished_at = None
        item.report_id = None
    if job.status in ("completed", "cancelled", "paused"):
        job.status = "paused"
        job.finished_at = None
    recount_job_stats(db, job)
    job.last_message = f"В очередь возвращено ошибок: {len(errors)}"
    job.updated_at = _utcnow()
    db.commit()
    db.refresh(job)
    return job


def drop_banks_from_job(db: Session, job_id: int) -> tuple[MassParseJob, int]:
    """Пометить pending/running bank-элементы как skipped (Грэм — отдельно)."""
    job = get_job(db, job_id)
    if not job:
        raise LookupError(f"Job {job_id} не найден")
    if job.status == "running" and is_worker_alive(job_id):
        raise ValueError("Сначала поставьте job на паузу")

    bank_company_ids = {
        int(c.id)
        for c in db.query(Company).all()
        if c.id is not None and sector_to_report_type(c.sector) == "bank"
    }
    bank_tickers = {
        str(c.ticker).strip().upper()
        for c in db.query(Company).all()
        if c.ticker and sector_to_report_type(c.sector) == "bank"
    }

    items = (
        db.query(MassParseItem)
        .filter(MassParseItem.job_id == job_id)
        .filter(MassParseItem.status.in_(("pending", "running")))
        .all()
    )
    n = 0
    now = _utcnow()
    for item in items:
        is_bank = (
            (item.company_id is not None and int(item.company_id) in bank_company_ids)
            or (item.ticker or "").strip().upper() in bank_tickers
        )
        if not is_bank:
            continue
        item.status = "skipped"
        item.message = "Банк/финсектор — вне массового Грэм-прогона"
        item.finished_at = now
        item.started_at = None
        n += 1

    recount_job_stats(db, job)
    job.last_message = f"Исключено банковских PDF из очереди: {n}"
    job.updated_at = now
    db.commit()
    db.refresh(job)
    return job, n
