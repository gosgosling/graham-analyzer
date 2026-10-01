"""События по бумаге: дивидендные отсечки и сплиты

Для засечек на графике цены. Выход отчётов берётся из
`financial_reports.disclosed_at`, сюда не дублируется.

Revision ID: e0f1a2b3c4d5
Revises: d9e0f1a2b3c4
Create Date: 2026-09-30
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e0f1a2b3c4d5"
down_revision: Union[str, None] = "d9e0f1a2b3c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "corporate_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("value", sa.Numeric(18, 6), nullable=True),
        sa.Column("currency", sa.String(8), nullable=True),
        sa.Column("source", sa.String(16), nullable=False, server_default="moex"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("company_id", "kind", "date", name="uq_corporate_event"),
    )
    op.create_index("ix_corporate_events_company_id", "corporate_events", ["company_id"])


def downgrade() -> None:
    op.drop_index("ix_corporate_events_company_id", table_name="corporate_events")
    op.drop_table("corporate_events")
