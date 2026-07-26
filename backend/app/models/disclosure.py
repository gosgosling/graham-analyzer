"""Модели мониторинга отчётности (e-disclosure ↔ сервис)."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class DisclosureSyncRun(Base):
    __tablename__ = "disclosure_sync_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # pending | running | ok | error
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    companies_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    companies_done: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    periods_found: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DisclosurePeriod(Base):
    __tablename__ = "disclosure_periods"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ticker: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    period_type: Mapped[str] = mapped_column(String(32), nullable=False)
    fiscal_year: Mapped[int] = mapped_column(Integer, nullable=False)
    fiscal_quarter: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    period_key: Mapped[str] = mapped_column(String(32), nullable=False)
    period_label: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    doc_type: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    published_at: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    file_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)

    on_edisclosure: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    in_db: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    on_disk: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_latest_interim: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # expected | optional | none
    expectation: Mapped[str] = mapped_column(String(32), nullable=False, default="none")
    # waiting | overdue | available | in_service | unknown
    coverage_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")

    pdf_path: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    report_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DisclosureParseJob(Base):
    """Очередь точечного парсинга PDF (без skip всего тикера)."""

    __tablename__ = "disclosure_parse_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # pending | running | paused | completed | cancelled
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    total_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    done_ok: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    done_error: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    done_skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class DisclosureParseItem(Base):
    __tablename__ = "disclosure_parse_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("disclosure_parse_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    disclosure_period_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    company_id: Mapped[int] = mapped_column(Integer, nullable=False)
    ticker: Mapped[str] = mapped_column(String(32), nullable=False)
    fiscal_year: Mapped[int] = mapped_column(Integer, nullable=False)
    period_type: Mapped[str] = mapped_column(String(32), nullable=False)
    fiscal_quarter: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    pdf_path: Mapped[str] = mapped_column(String(2048), nullable=False)
    # pending | running | success | skipped | error | cancelled
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    report_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
