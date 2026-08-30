"""market_assumptions — допущения об уровне рынка для базового множителя

Revision ID: b1c2d3e4f5a6
Revises: a0b1c2d3e4f5
"""
from alembic import op
import sqlalchemy as sa

revision = "b1c2d3e4f5a6"
down_revision = "a0b1c2d3e4f5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "market_assumptions",
        sa.Column("year", sa.Integer(), primary_key=True),
        sa.Column("risk_free_rate", sa.Numeric(6, 2), nullable=False),
        sa.Column("risk_premium", sa.Numeric(6, 2), nullable=False),
        sa.Column("dividend_growth", sa.Numeric(6, 2), nullable=False),
        sa.Column("payout", sa.Numeric(6, 2), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("source", sa.String(16), nullable=False, server_default="manual"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_table("market_assumptions")
