"""multipliers: pb_tangible, goodwill, goodwill_to_assets

Revision ID: c6d7e8f9a0b1
Revises: b5c6d7e8f9a0
"""
from alembic import op
import sqlalchemy as sa

revision = "c6d7e8f9a0b1"
down_revision = "b5c6d7e8f9a0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("multipliers", sa.Column("pb_tangible", sa.Numeric(12, 4), nullable=True))
    op.add_column("multipliers", sa.Column("goodwill", sa.Numeric(20, 2), nullable=True))
    op.add_column("multipliers", sa.Column("goodwill_to_assets", sa.Numeric(8, 2), nullable=True))


def downgrade() -> None:
    for col in ("goodwill_to_assets", "goodwill", "pb_tangible"):
        op.drop_column("multipliers", col)
