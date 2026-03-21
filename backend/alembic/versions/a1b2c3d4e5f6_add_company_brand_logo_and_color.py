"""add company brand_logo_url and brand_color

Revision ID: a1b2c3d4e5f6
Revises: 6e096f66805d
Create Date: 2026-03-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '6e096f66805d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'companies',
        sa.Column('brand_logo_url', sa.String(length=512), nullable=True),
    )
    op.add_column(
        'companies',
        sa.Column('brand_color', sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('companies', 'brand_color')
    op.drop_column('companies', 'brand_logo_url')
