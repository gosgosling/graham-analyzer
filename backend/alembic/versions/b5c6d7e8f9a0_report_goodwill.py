"""financial_reports.goodwill — гудвил для расчёта материального капитала

Revision ID: b5c6d7e8f9a0
Revises: a4b5c6d7e8f9
"""
from alembic import op
import sqlalchemy as sa

revision = "b5c6d7e8f9a0"
down_revision = "a4b5c6d7e8f9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("financial_reports", sa.Column("goodwill", sa.Numeric(15, 3), nullable=True))


def downgrade() -> None:
    op.drop_column("financial_reports", "goodwill")
