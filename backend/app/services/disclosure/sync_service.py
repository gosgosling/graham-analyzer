"""Синхронизация listing e-disclosure → disclosure_periods."""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.company import Company
from app.models.disclosure import DisclosurePeriod, DisclosureSyncRun
from app.models.financial_report import FinancialReport
from app.services.disclosure.calendar import (
    compute_coverage_status,
    expected_periods_for_today,
)
from app.services.disclosure.edisclosure_client import (
    fetch_company_reports,
    filter_coverage,
    load_edisclosure_mapping,
)
from app.services.disclosure.paths import interim_rank, pdf_path_for, period_key

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_thread: Optional[threading.Thread] = None
_active_run_id: Optional[int] = None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def is_sync_alive() -> bool:
    with _lock:
        return _thread is not None and _thread.is_alive()


def get_latest_run(db: Session) -> Optional[DisclosureSyncRun]:
    return (
        db.query(DisclosureSyncRun)
        .order_by(DisclosureSyncRun.id.desc())
        .first()
    )


def start_sync(db: Session, *, tickers: Optional[list[str]] = None) -> DisclosureSyncRun:
    global _thread, _active_run_id
    with _lock:
        if _thread is not None and _thread.is_alive():
            raise RuntimeError("Синхронизация уже выполняется")

        run = DisclosureSyncRun(
            status="pending",
            created_at=_utcnow(),
            last_message="Ожидание запуска…",
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        run_id = int(run.id)
        _active_run_id = run_id
        _thread = threading.Thread(
            target=_sync_loop,
            args=(run_id, tickers),
            name=f"disclosure-sync-{run_id}",
            daemon=True,
        )
        _thread.start()
        return run


def _sync_loop(run_id: int, tickers: Optional[list[str]]) -> None:
    global _active_run_id
    db = SessionLocal()
    try:
        run = db.query(DisclosureSyncRun).filter(DisclosureSyncRun.id == run_id).first()
        if not run:
            return
        run.status = "running"
        run.started_at = _utcnow()
        run.last_message = "Загрузка маппинга e-disclosure…"
        db.commit()

        mapping = load_edisclosure_mapping()
        q = db.query(Company)
        companies = q.all()
        work: list[tuple[Company, int]] = []
        ticker_filter = {t.upper() for t in tickers} if tickers else None
        for c in companies:
            if not c.ticker:
                continue
            t = str(c.ticker).strip().upper()
            if ticker_filter and t not in ticker_filter:
                continue
            eid = mapping.get(t)
            if eid is None:
                continue
            work.append((c, eid))

        run.companies_total = len(work)
        run.last_message = f"Компаний к обходу: {len(work)}"
        db.commit()

        periods_found = 0
        blocked_msgs: list[str] = []
        for idx, (company, eid) in enumerate(work, start=1):
            ticker = str(company.ticker).strip().upper()
            try:
                raw = fetch_company_reports(eid, ticker)
                covered = filter_coverage(raw)
                n = _upsert_company_periods(db, company, covered, raw)
                periods_found += n
            except Exception as exc:  # noqa: BLE001
                msg = str(exc)
                logger.exception("Disclosure sync %s: %s", ticker, exc)
                run.last_message = f"Ошибка {ticker}: {msg}"[:500]
                db.commit()
                if "ServicePipe" in msg or "captcha" in msg.lower():
                    blocked_msgs.append(msg)
                    # Дальше почти наверняка та же блокировка — прерываем обход
                    run.companies_done = idx
                    run.periods_found = periods_found
                    db.commit()
                    break

            run.companies_done = idx
            run.periods_found = periods_found
            run.last_message = f"{idx}/{len(work)} {ticker} (+{periods_found} периодов)"
            db.commit()

        # Календарные ожидания без e-disclosure (waiting/overdue stubs)
        _ensure_expectation_stubs(db)

        # Пересчёт флагов in_db / on_disk / status для всех
        _refresh_all_flags(db)

        run.finished_at = _utcnow()
        if blocked_msgs and periods_found == 0:
            run.status = "error"
            run.last_message = blocked_msgs[0][:1000]
        else:
            run.status = "ok"
            suffix = ""
            if blocked_msgs:
                suffix = " (частично: ServicePipe)"
            run.last_message = (
                f"Готово: компаний {run.companies_done}, "
                f"периодов coverage {periods_found}{suffix}"
            )
        db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Disclosure sync crashed: %s", exc)
        run = db.query(DisclosureSyncRun).filter(DisclosureSyncRun.id == run_id).first()
        if run:
            run.status = "error"
            run.finished_at = _utcnow()
            run.last_message = str(exc)[:1000]
            db.commit()
    finally:
        try:
            from app.services.disclosure.edisclosure_client import close_browser_session

            close_browser_session()
        except Exception:  # noqa: BLE001
            pass
        db.close()
        with _lock:
            if _active_run_id == run_id:
                _active_run_id = None


def _upsert_company_periods(
    db: Session,
    company: Company,
    covered: list[dict],
    all_raw: list[dict],
) -> int:
    """Пишет coverage-filtered периоды; помечает latest interim."""
    now = _utcnow()
    ticker = str(company.ticker).strip().upper()
    company_id = int(company.id)  # type: ignore[arg-type]

    # Сбросить is_latest_interim для компании
    db.query(DisclosurePeriod).filter(
        DisclosurePeriod.company_id == company_id
    ).update({"is_latest_interim": False})

    interims = [e for e in covered if e.get("period_type") != "annual"]
    latest_key = None
    if interims:
        best = max(
            interims,
            key=lambda e: (
                int(e["fiscal_year"]),
                int(e.get("interim_rank") or interim_rank(e["period_type"], e.get("fiscal_quarter"))),
            ),
        )
        latest_key = (
            best["period_type"],
            int(best["fiscal_year"]),
            best.get("fiscal_quarter"),
        )

    n = 0
    for e in covered:
        pt = e["period_type"]
        fy = int(e["fiscal_year"])
        fq = e.get("fiscal_quarter")
        row = (
            db.query(DisclosurePeriod)
            .filter(DisclosurePeriod.company_id == company_id)
            .filter(DisclosurePeriod.period_type == pt)
            .filter(DisclosurePeriod.fiscal_year == fy)
            .filter(
                DisclosurePeriod.fiscal_quarter.is_(None)
                if fq is None
                else DisclosurePeriod.fiscal_quarter == fq
            )
            .first()
        )
        if row is None:
            row = DisclosurePeriod(
                company_id=company_id,
                ticker=ticker,
                period_type=pt,
                fiscal_year=fy,
                fiscal_quarter=fq,
                period_key=e.get("period_key") or period_key(pt, fy, fq),
                expectation="none",
                coverage_status="unknown",
                updated_at=now,
            )
            db.add(row)

        row.ticker = ticker
        row.period_key = e.get("period_key") or period_key(pt, fy, fq)
        row.period_label = e.get("period") or e.get("period_label")
        row.doc_type = e.get("doc_type")
        row.published_at = e.get("published_at")
        row.file_url = e.get("file_url")
        row.on_edisclosure = True
        row.is_latest_interim = (
            pt != "annual" and latest_key == (pt, fy, fq)
        )
        row.last_seen_at = now
        row.updated_at = now
        n += 1

    db.commit()
    return n


def _ensure_expectation_stubs(db: Session) -> None:
    """Для каждой компании с mapping создать ожидаемые периоды, если ещё нет."""
    mapping = load_edisclosure_mapping()
    expected = expected_periods_for_today()
    now = _utcnow()
    companies = db.query(Company).all()
    for c in companies:
        if not c.ticker:
            continue
        t = str(c.ticker).strip().upper()
        if t not in mapping:
            continue
        cid = int(c.id)  # type: ignore[arg-type]
        for exp in expected:
            pt = exp["period_type"]
            fy = exp["fiscal_year"]
            fq = exp["fiscal_quarter"]
            row = (
                db.query(DisclosurePeriod)
                .filter(DisclosurePeriod.company_id == cid)
                .filter(DisclosurePeriod.period_type == pt)
                .filter(DisclosurePeriod.fiscal_year == fy)
                .filter(
                    DisclosurePeriod.fiscal_quarter.is_(None)
                    if fq is None
                    else DisclosurePeriod.fiscal_quarter == fq
                )
                .first()
            )
            if row is None:
                row = DisclosurePeriod(
                    company_id=cid,
                    ticker=t,
                    period_type=pt,
                    fiscal_year=fy,
                    fiscal_quarter=fq,
                    period_key=period_key(pt, fy, fq),
                    on_edisclosure=False,
                    expectation="expected",
                    coverage_status="waiting",
                    updated_at=now,
                )
                db.add(row)
            else:
                row.expectation = "expected"
                row.updated_at = now
    db.commit()


def _refresh_all_flags(db: Session) -> None:
    today = datetime.now().date()
    expected_map = {
        (e["period_type"], e["fiscal_year"], e["fiscal_quarter"]): e["expectation_start"]
        for e in expected_periods_for_today(today)
    }

    rows = db.query(DisclosurePeriod).all()
    # preload reports
    report_keys: set[tuple] = set()
    report_ids: dict[tuple, int] = {}
    for r in db.query(FinancialReport).all():
        pt = r.period_type
        if hasattr(pt, "value"):
            pt = pt.value
        key = (
            int(r.company_id),  # type: ignore[arg-type]
            str(pt),
            int(r.fiscal_year),  # type: ignore[arg-type]
            r.fiscal_quarter,
        )
        report_keys.add(key)
        report_ids[key] = int(r.id)  # type: ignore[arg-type]

    now = _utcnow()
    for row in rows:
        key = (row.company_id, row.period_type, row.fiscal_year, row.fiscal_quarter)
        row.in_db = key in report_keys
        row.report_id = report_ids.get(key)
        path = pdf_path_for(
            row.ticker, row.period_type, row.fiscal_year, row.fiscal_quarter
        )
        row.on_disk = path.is_file()
        row.pdf_path = str(path) if row.on_disk else row.pdf_path
        exp_start = expected_map.get(
            (row.period_type, row.fiscal_year, row.fiscal_quarter)
        )
        if exp_start is not None:
            row.expectation = "expected"
        row.coverage_status = compute_coverage_status(
            in_db=row.in_db,
            on_edisclosure=row.on_edisclosure,
            expectation=row.expectation,
            expectation_start=exp_start,
            today=today,
        )
        row.updated_at = now
    db.commit()


def refresh_flags_only(db: Session) -> int:
    """Быстрый пересчёт in_db/on_disk без e-disclosure."""
    _refresh_all_flags(db)
    return db.query(DisclosurePeriod).count()


def import_listing(
    db: Session,
    items: list[dict],
    *,
    apply_coverage_filter: bool = True,
) -> dict:
    """
    Импорт listing (обход ServicePipe): items — dict как ReportEntry.to_dict()
    плюс обязательный ключ ticker.
    """
    by_ticker: dict[str, list[dict]] = {}
    for it in items:
        t = str(it.get("ticker") or "").strip().upper()
        if not t:
            continue
        by_ticker.setdefault(t, []).append(it)

    companies = {
        str(c.ticker).strip().upper(): c
        for c in db.query(Company).all()
        if c.ticker
    }
    imported = 0
    skipped_tickers: list[str] = []
    for ticker, raw in by_ticker.items():
        company = companies.get(ticker)
        if not company:
            skipped_tickers.append(ticker)
            continue
        covered = filter_coverage(raw) if apply_coverage_filter else raw
        imported += _upsert_company_periods(db, company, covered, raw)

    _ensure_expectation_stubs(db)
    _refresh_all_flags(db)
    return {
        "imported": imported,
        "tickers": sorted(by_ticker.keys()),
        "skipped_tickers": skipped_tickers,
    }
