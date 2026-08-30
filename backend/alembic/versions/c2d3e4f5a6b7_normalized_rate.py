"""market_assumptions.normalized_risk_free_rate — ставка вне пика цикла

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
"""
from alembic import op
import sqlalchemy as sa

revision = "c2d3e4f5a6b7"
down_revision = "b1c2d3e4f5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "market_assumptions",
        sa.Column("normalized_risk_free_rate", sa.Numeric(6, 2), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("market_assumptions", "normalized_risk_free_rate")
