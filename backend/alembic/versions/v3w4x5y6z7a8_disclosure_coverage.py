"""Мониторинг отчётности e-disclosure

Revision ID: v3w4x5y6z7a8
Revises: u2v3w4x5y6z7
Create Date: 2026-07-26
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v3w4x5y6z7a8"
down_revision: Union[str, Sequence[str], None] = "u2v3w4x5y6z7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "disclosure_sync_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("companies_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("companies_done", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("periods_found", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "disclosure_periods",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "company_id",
            sa.Integer(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ticker", sa.String(32), nullable=False),
        sa.Column("period_type", sa.String(32), nullable=False),
        sa.Column("fiscal_year", sa.Integer(), nullable=False),
        sa.Column("fiscal_quarter", sa.Integer(), nullable=True),
        sa.Column("period_key", sa.String(32), nullable=False),
        sa.Column("period_label", sa.String(128), nullable=True),
        sa.Column("doc_type", sa.String(256), nullable=True),
        sa.Column("published_at", sa.String(64), nullable=True),
        sa.Column("file_url", sa.String(1024), nullable=True),
        sa.Column("on_edisclosure", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("in_db", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("on_disk", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "is_latest_interim", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("expectation", sa.String(32), nullable=False, server_default="none"),
        sa.Column("coverage_status", sa.String(32), nullable=False, server_default="unknown"),
        sa.Column("pdf_path", sa.String(2048), nullable=True),
        sa.Column("report_id", sa.Integer(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_disclosure_periods_company_id", "disclosure_periods", ["company_id"])
    op.create_index("ix_disclosure_periods_ticker", "disclosure_periods", ["ticker"])
    op.create_index(
        "ix_disclosure_periods_coverage_status", "disclosure_periods", ["coverage_status"]
    )
    # NULL fiscal_quarter для annual/H1 — уникальность через COALESCE
    op.execute(
        """
        CREATE UNIQUE INDEX uq_disclosure_period_coalesce
        ON disclosure_periods (
            company_id,
            period_type,
            fiscal_year,
            COALESCE(fiscal_quarter, 0)
        )
        """
    )

    op.create_table(
        "disclosure_parse_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("total_items", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("done_ok", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("done_error", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("done_skipped", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "disclosure_parse_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "job_id",
            sa.Integer(),
            sa.ForeignKey("disclosure_parse_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("disclosure_period_id", sa.Integer(), nullable=True),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.String(32), nullable=False),
        sa.Column("fiscal_year", sa.Integer(), nullable=False),
        sa.Column("period_type", sa.String(32), nullable=False),
        sa.Column("fiscal_quarter", sa.Integer(), nullable=True),
        sa.Column("pdf_path", sa.String(2048), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("report_id", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_disclosure_parse_items_job_id", "disclosure_parse_items", ["job_id"])


def downgrade() -> None:
    op.drop_index("ix_disclosure_parse_items_job_id", table_name="disclosure_parse_items")
    op.drop_table("disclosure_parse_items")
    op.drop_table("disclosure_parse_jobs")
    op.execute("DROP INDEX IF EXISTS uq_disclosure_period_coalesce")
    op.drop_index("ix_disclosure_periods_coverage_status", table_name="disclosure_periods")
    op.drop_index("ix_disclosure_periods_ticker", table_name="disclosure_periods")
    op.drop_index("ix_disclosure_periods_company_id", table_name="disclosure_periods")
    op.drop_table("disclosure_periods")
    op.drop_table("disclosure_sync_runs")
