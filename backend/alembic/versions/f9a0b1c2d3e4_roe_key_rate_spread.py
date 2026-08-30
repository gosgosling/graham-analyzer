"""multipliers.key_rate и roe_spread — отдача капитала сверх безрисковой

Revision ID: f9a0b1c2d3e4
Revises: e8f9a0b1c2d3
"""
from alembic import op
import sqlalchemy as sa

revision = "f9a0b1c2d3e4"
down_revision = "e8f9a0b1c2d3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("multipliers", sa.Column("key_rate", sa.Numeric(8, 2), nullable=True))
    op.add_column("multipliers", sa.Column("roe_spread", sa.Numeric(10, 2), nullable=True))


def downgrade() -> None:
    op.drop_column("multipliers", "roe_spread")
    op.drop_column("multipliers", "key_rate")
