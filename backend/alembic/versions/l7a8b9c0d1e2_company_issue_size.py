"""Выпуск акций по реестру Мосбиржи — сегодняшний, для текущих мультипликаторов

Revision ID: l7a8b9c0d1e2
Revises: k6f7a8b9c0d1
Create Date: 2026-10-02
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "l7a8b9c0d1e2"
down_revision: Union[str, None] = "k6f7a8b9c0d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("companies", sa.Column("issue_size", sa.BigInteger(), nullable=True))
    op.add_column("companies", sa.Column("issue_size_at", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("companies", "issue_size_at")
    op.drop_column("companies", "issue_size")
