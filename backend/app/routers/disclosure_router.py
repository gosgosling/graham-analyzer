"""API мониторинга отчётности e-disclosure."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.company import Company
from app.models.disclosure import DisclosureParseJob, DisclosurePeriod, DisclosureSyncRun
from app.models.financial_report import FinancialReport
from app.services.analysis.report_expectations import expected_periods, upcoming_reports
from app.services.disclosure import parse_queue, sync_service

router = APIRouter(prefix="/disclosure", tags=["disclosure"])


class SyncRunOut(BaseModel):
    id: int
    status: str
    companies_total: int
    companies_done: int
    periods_found: int
    last_message: Optional[str] = None
    worker_alive: bool = False
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class CoverageItemOut(BaseModel):
    id: int
    company_id: int
    ticker: str
    period_type: str
    fiscal_year: int
    fiscal_quarter: Optional[int] = None
    period_key: str
    period_label: Optional[str] = None
    doc_type: Optional[str] = None
    published_at: Optional[str] = None
    on_edisclosure: bool
    in_db: bool
    on_disk: bool
    is_latest_interim: bool
    expectation: str
    coverage_status: str
    file_url: Optional[str] = None
    pdf_path: Optional[str] = None
    report_id: Optional[int] = None

    model_config = {"from_attributes": True}


class CoverageSummaryOut(BaseModel):
    total: int
    waiting: int
    overdue: int
    available: int
    in_service: int
    unknown: int
    last_sync: Optional[SyncRunOut] = None


class IdsIn(BaseModel):
    period_ids: List[int] = Field(..., min_length=1)


class SyncIn(BaseModel):
    tickers: Optional[List[str]] = None


class ImportListingIn(BaseModel):
    """Элементы как вывод scraper --list-json (+ поле ticker)."""
    items: List[dict]
    apply_coverage_filter: bool = True


class ParseJobOut(BaseModel):
    id: int
    status: str
    total_items: int
    done_ok: int
    done_error: int
    done_skipped: int
    last_message: Optional[str] = None
    worker_alive: bool = False

    model_config = {"from_attributes": True}


def _sync_out(run: DisclosureSyncRun) -> SyncRunOut:
    return SyncRunOut(
        id=run.id,
        status=run.status,
        companies_total=run.companies_total,
        companies_done=run.companies_done,
        periods_found=run.periods_found,
        last_message=run.last_message,
        worker_alive=sync_service.is_sync_alive(),
        started_at=run.started_at,
        finished_at=run.finished_at,
        created_at=run.created_at,
    )


class ExpectedPeriodOut(BaseModel):
    """Ожидаемый период с точки зрения нашей базы, без внешних источников."""

    company_id: int
    ticker: str
    name: Optional[str] = None
    period_type: str
    fiscal_year: int
    fiscal_quarter: Optional[int] = None
    period_key: str
    period_label: str
    period_end: date
    deadline: date
    status: str
    days_overdue: Optional[int] = None
    report_id: Optional[int] = None


class ExpectationsOut(BaseModel):
    total: int
    filed: int
    window_open: int
    overdue: int
    companies_with_gaps: int
    items: List[ExpectedPeriodOut]


class UpcomingReportOut(BaseModel):
    company_id: int
    ticker: str
    name: Optional[str] = None
    logo_url: Optional[str] = None
    period_type: str
    fiscal_year: int
    fiscal_quarter: Optional[int] = None
    period_key: str
    period_label: str
    period_end: date
    expected_date: date
    confidence: str
    lag_days: int
    lag_spread: Optional[int] = None
    samples: int


class CalendarDayOut(BaseModel):
    day: date
    items: List[UpcomingReportOut]


class CalendarOut(BaseModel):
    today: date
    horizon_days: int
    total: int
    days: List[CalendarDayOut]


@router.get("/calendar", response_model=CalendarOut)
def calendar(
    days: int = Query(150, ge=7, le=400, description="Горизонт прогноза, дней"),
    confidence: Optional[str] = Query(
        None, description="narrow | wide | rough — фильтр по точности прогноза"
    ),
    db: Session = Depends(get_db),
):
    """
    Календарь ожидаемых публикаций.

    Точной даты будущей публикации не существует: закон обязывает раскрыть
    отчётность не позднее срока, но не обязывает объявлять день заранее.
    Поэтому здесь прогноз, и он честно помечен своей точностью:

        narrow  компания публикует стабильно — можно называть датой
        wide    разброс до месяца — ориентир, не дата
        rough   разброс больше месяца или истории нет — только месяц

    Прогноз переносится на рабочий день: в субботу отчётность не публикует
    никто, а календари, переносящие прошлогоднюю дату календарно, регулярно
    показывают десятки эмитентов в выходной.
    """
    companies = {c.id: c for c in db.query(Company).all()}
    by_company = defaultdict(list)
    for rep in db.query(FinancialReport).all():
        by_company[rep.company_id].append(rep)

    grouped: dict[date, List[UpcomingReportOut]] = defaultdict(list)
    total = 0
    for company_id, reports in by_company.items():
        company = companies.get(company_id)
        if company is None:
            continue
        for item in upcoming_reports(reports, horizon_days=days):
            if confidence and item.confidence != confidence:
                continue
            total += 1
            grouped[item.expected_date].append(
                UpcomingReportOut(
                    company_id=company_id,
                    ticker=str(company.ticker),
                    name=str(company.name) if company.name else None,
                    logo_url=str(company.brand_logo_url) if company.brand_logo_url else None,
                    period_type=item.period_type,
                    fiscal_year=item.fiscal_year,
                    fiscal_quarter=item.fiscal_quarter,
                    period_key=item.period_key,
                    period_label=item.period_label,
                    period_end=item.period_end,
                    expected_date=item.expected_date,
                    confidence=item.confidence,
                    lag_days=item.lag_days,
                    lag_spread=item.lag_spread,
                    samples=item.samples,
                )
            )

    out_days = [
        CalendarDayOut(day=d, items=sorted(v, key=lambda i: i.ticker))
        for d, v in sorted(grouped.items())
    ]
    return CalendarOut(
        today=date.today(), horizon_days=days, total=total, days=out_days
    )


@router.get("/expectations", response_model=ExpectationsOut)
def expectations(
    status: Optional[str] = Query(
        "overdue", description="overdue | window_open | filed | all"
    ),
    limit: int = Query(200, ge=1, le=2000),
    db: Session = Depends(get_db),
):
    """
    Чего не хватает в базе — по её собственным данным.

    Ни одного обращения к центру раскрытия. Ожидание периода выводится из
    истории самой компании, срок — из её же медианной задержки публикации.
    Отсюда и порядок выдачи: самые свежие пропуски первыми, потому что их
    отчёты уже опубликованы и лежат на сайте эмитента.
    """
    companies = {c.id: c for c in db.query(Company).all()}
    by_company = defaultdict(list)
    for rep in db.query(FinancialReport).all():
        by_company[rep.company_id].append(rep)

    counts = {"filed": 0, "window_open": 0, "overdue": 0}
    gap_companies: set[int] = set()
    items: List[ExpectedPeriodOut] = []
    today = date.today()

    for company_id, reports in by_company.items():
        company = companies.get(company_id)
        if company is None:
            continue
        for period in expected_periods(reports, today=today):
            counts[period.status] = counts.get(period.status, 0) + 1
            if period.status == "overdue":
                gap_companies.add(company_id)
            if status not in (None, "all") and period.status != status:
                continue
            items.append(
                ExpectedPeriodOut(
                    company_id=company_id,
                    ticker=str(company.ticker),
                    name=str(company.name) if company.name else None,
                    period_type=period.period_type,
                    fiscal_year=period.fiscal_year,
                    fiscal_quarter=period.fiscal_quarter,
                    period_key=period.period_key,
                    period_label=period.period_label,
                    period_end=period.period_end,
                    deadline=period.deadline,
                    status=period.status,
                    days_overdue=period.days_overdue,
                    report_id=period.report_id,
                )
            )

    # Свежий пропуск ценнее старого: его отчёт уже вышел и его можно внести
    # сегодня. Давние пропуски часто означают, что компания тогда просто не
    # отчитывалась, и лезть за ними некуда.
    items.sort(key=lambda i: (i.days_overdue if i.days_overdue is not None else 10**6,
                              i.ticker))

    return ExpectationsOut(
        total=sum(counts.values()),
        filed=counts.get("filed", 0),
        window_open=counts.get("window_open", 0),
        overdue=counts.get("overdue", 0),
        companies_with_gaps=len(gap_companies),
        items=items[:limit],
    )


@router.get("/summary", response_model=CoverageSummaryOut)
def summary(db: Session = Depends(get_db)):
    # Флаги in_db / on_disk / coverage_status хранятся в таблице, а не считаются
    # на лету. Значит после каждого внесённого отчёта они устаревают, и экран
    # показывает «нет в базе» по отчёту, который в базе есть. Пересчёт локальный
    # (никакого e-disclosure) и стоит миллисекунды, поэтому делаем его на чтении,
    # а не оставляем на кнопку, которую никто не нажимает.
    sync_service.refresh_flags_only(db)
    rows = db.query(DisclosurePeriod).all()
    counts = {"waiting": 0, "overdue": 0, "available": 0, "in_service": 0, "unknown": 0}
    for r in rows:
        counts[r.coverage_status] = counts.get(r.coverage_status, 0) + 1
    last = sync_service.get_latest_run(db)
    return CoverageSummaryOut(
        total=len(rows),
        waiting=counts.get("waiting", 0),
        overdue=counts.get("overdue", 0),
        available=counts.get("available", 0),
        in_service=counts.get("in_service", 0),
        unknown=counts.get("unknown", 0),
        last_sync=_sync_out(last) if last else None,
    )


@router.get("/coverage", response_model=List[CoverageItemOut])
def coverage(
    mode: str = Query("missing", description="missing | expected | all"),
    status: Optional[str] = Query(None),
    ticker: Optional[str] = Query(None),
    period_type: Optional[str] = Query(None),
    limit: int = Query(500, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    # Тот же пересчёт, что и в summary: иначе список показывает пропуски
    # по отчётам, которые уже внесены.
    sync_service.refresh_flags_only(db)
    q = db.query(DisclosurePeriod)
    if ticker:
        q = q.filter(DisclosurePeriod.ticker == ticker.strip().upper())
    if period_type:
        q = q.filter(DisclosurePeriod.period_type == period_type)
    if status:
        q = q.filter(DisclosurePeriod.coverage_status == status)

    if mode == "missing":
        # на e-disclosure, нет в БД; interim только latest
        q = q.filter(DisclosurePeriod.on_edisclosure.is_(True))
        q = q.filter(DisclosurePeriod.in_db.is_(False))
        q = q.filter(
            (DisclosurePeriod.period_type == "annual")
            | (DisclosurePeriod.is_latest_interim.is_(True))
        )
    elif mode == "expected":
        q = q.filter(DisclosurePeriod.expectation == "expected")

    rows = (
        q.order_by(
            DisclosurePeriod.ticker.asc(),
            DisclosurePeriod.fiscal_year.desc(),
            DisclosurePeriod.period_type.asc(),
        )
        .offset(offset)
        .limit(limit)
        .all()
    )
    return rows


@router.get("/sync/status", response_model=Optional[SyncRunOut])
def sync_status(db: Session = Depends(get_db)):
    run = sync_service.get_latest_run(db)
    return _sync_out(run) if run else None


@router.post("/sync", response_model=SyncRunOut)
def sync_start(body: SyncIn = SyncIn(), db: Session = Depends(get_db)):
    try:
        run = sync_service.start_sync(db, tickers=body.tickers)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _sync_out(run)


@router.post("/refresh-flags")
def refresh_flags(db: Session = Depends(get_db)):
    n = sync_service.refresh_flags_only(db)
    return {"updated": n}


@router.post("/import-listing")
def import_listing(body: ImportListingIn, db: Session = Depends(get_db)):
    """Импорт listing JSON (когда live Playwright блокирует ServicePipe)."""
    if not body.items:
        raise HTTPException(status_code=400, detail="items пуст")
    return sync_service.import_listing(
        db, body.items, apply_coverage_filter=body.apply_coverage_filter
    )


@router.post("/download")
def download(body: IdsIn, db: Session = Depends(get_db)):
    try:
        return parse_queue.download_periods(db, body.period_ids)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/enqueue-parse", response_model=ParseJobOut)
def enqueue_parse(body: IdsIn, db: Session = Depends(get_db)):
    try:
        job = parse_queue.enqueue_parse(db, body.period_ids, auto_start=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ParseJobOut(
        id=job.id,
        status=job.status,
        total_items=job.total_items,
        done_ok=job.done_ok,
        done_error=job.done_error,
        done_skipped=job.done_skipped,
        last_message=job.last_message,
        worker_alive=parse_queue.is_parse_worker_alive(job.id),
    )


@router.get("/parse-jobs/{job_id}", response_model=ParseJobOut)
def get_parse_job(job_id: int, db: Session = Depends(get_db)):
    job = db.query(DisclosureParseJob).filter(DisclosureParseJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job не найден")
    return ParseJobOut(
        id=job.id,
        status=job.status,
        total_items=job.total_items,
        done_ok=job.done_ok,
        done_error=job.done_error,
        done_skipped=job.done_skipped,
        last_message=job.last_message,
        worker_alive=parse_queue.is_parse_worker_alive(job.id),
    )
