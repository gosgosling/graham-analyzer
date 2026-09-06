"""market_assumptions.long_run_growth — потолок устойчивого роста

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
"""
from alembic import op
import sqlalchemy as sa

revision = "d3e4f5a6b7c8"
down_revision = "c2d3e4f5a6b7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "market_assumptions",
        sa.Column("long_run_growth", sa.Numeric(6, 2), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("market_assumptions", "long_run_growth")
