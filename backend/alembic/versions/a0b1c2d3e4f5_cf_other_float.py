"""financial_reports.cf_other_float — второй пул чужих денег в ОДДС

Revision ID: a0b1c2d3e4f5
Revises: f9a0b1c2d3e4
"""
from alembic import op
import sqlalchemy as sa

revision = "a0b1c2d3e4f5"
down_revision = "f9a0b1c2d3e4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "financial_reports",
        sa.Column("cf_other_float", sa.Numeric(15, 3), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("financial_reports", "cf_other_float")
