"""multipliers.eps — точность до шести знаков для копеечных бумаг

Revision ID: e8f9a0b1c2d3
Revises: d7e8f9a0b1c2
"""
from alembic import op
import sqlalchemy as sa

revision = "e8f9a0b1c2d3"
down_revision = "d7e8f9a0b1c2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("multipliers", "eps", type_=sa.Numeric(18, 6), existing_nullable=True)


def downgrade() -> None:
    op.alter_column("multipliers", "eps", type_=sa.Numeric(15, 2), existing_nullable=True)
