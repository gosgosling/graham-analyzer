"""multipliers.eps — прибыль на акцию

Revision ID: d7e8f9a0b1c2
Revises: c6d7e8f9a0b1
"""
from alembic import op
import sqlalchemy as sa

revision = "d7e8f9a0b1c2"
down_revision = "c6d7e8f9a0b1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("multipliers", sa.Column("eps", sa.Numeric(15, 2), nullable=True))


def downgrade() -> None:
    op.drop_column("multipliers", "eps")
