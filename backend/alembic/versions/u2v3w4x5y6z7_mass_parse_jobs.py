"""Массовый AI-парсинг PDF: jobs + items

Revision ID: u2v3w4x5y6z7
Revises: t1u2v3w4x5y6
Create Date: 2026-07-26
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "u2v3w4x5y6z7"
down_revision: Union[str, Sequence[str], None] = "t1u2v3w4x5y6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "mass_parse_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("reports_root", sa.String(1024), nullable=False),
        sa.Column(
            "skip_companies_with_reports",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("force", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "accounting_standard",
            sa.String(32),
            nullable=False,
            server_default="IFRS",
        ),
        sa.Column(
            "consolidated",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("total_items", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("done_ok", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("done_skipped", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("done_error", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("current_item_id", sa.Integer(), nullable=True),
        sa.Column("last_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_mass_parse_jobs_status", "mass_parse_jobs", ["status"])

    op.create_table(
        "mass_parse_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "job_id",
            sa.Integer(),
            sa.ForeignKey("mass_parse_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.String(32), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=True),
        sa.Column("fiscal_year", sa.Integer(), nullable=True),
        sa.Column("pdf_path", sa.String(2048), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("report_id", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_mass_parse_items_job_id", "mass_parse_items", ["job_id"])
    op.create_index(
        "ix_mass_parse_items_job_status",
        "mass_parse_items",
        ["job_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_mass_parse_items_job_status", table_name="mass_parse_items")
    op.drop_index("ix_mass_parse_items_job_id", table_name="mass_parse_items")
    op.drop_table("mass_parse_items")
    op.drop_index("ix_mass_parse_jobs_status", table_name="mass_parse_jobs")
    op.drop_table("mass_parse_jobs")
