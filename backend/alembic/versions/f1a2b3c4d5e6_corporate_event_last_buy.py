"""Последний день покупки с дивидендом

Засечка дивиденда на графике ставится на первый день без него — там цена
делает гэп. Дата реестра остаётся в `date`.

Revision ID: f1a2b3c4d5e6
Revises: e0f1a2b3c4d5
Create Date: 2026-09-30
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, None] = "e0f1a2b3c4d5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("corporate_events", sa.Column("last_buy_date", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("corporate_events", "last_buy_date")
