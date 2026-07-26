"""Модели очереди массового AI-парсинга PDF с диска."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class MassParseJob(Base):
    __tablename__ = "mass_parse_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # pending | running | paused | completed | cancelled
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    reports_root: Mapped[str] = mapped_column(String(1024), nullable=False)
    skip_companies_with_reports: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    force: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    accounting_standard: Mapped[str] = mapped_column(String(32), nullable=False, default="IFRS")
    consolidated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    total_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    done_ok: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    done_skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    done_error: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    current_item_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    last_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    items: Mapped[list["MassParseItem"]] = relationship(
        "MassParseItem",
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="MassParseItem.position",
    )


class MassParseItem(Base):
    __tablename__ = "mass_parse_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("mass_parse_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    ticker: Mapped[str] = mapped_column(String(32), nullable=False)
    company_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    fiscal_year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    pdf_path: Mapped[str] = mapped_column(String(2048), nullable=False)
    # pending | running | success | skipped | error | cancelled
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    report_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    job: Mapped["MassParseJob"] = relationship("MassParseJob", back_populates="items")
