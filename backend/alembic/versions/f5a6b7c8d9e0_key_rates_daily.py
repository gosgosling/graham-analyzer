"""Ключевая ставка ЦБ по дням

Оценка на графике считалась по средней ставке за год, и весь год вставал в
одинаковые условия — хотя в 2015-м ставка шла от 17% до 11%. Дневной ряд
позволяет считать оценку по той ставке, что действовала в тот день.

Revision ID: f5a6b7c8d9e0
Revises: e4f5a6b7c8d9
Create Date: 2026-09-26
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f5a6b7c8d9e0"
down_revision: Union[str, None] = "e4f5a6b7c8d9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "key_rates_daily",
        sa.Column("date", sa.Date(), primary_key=True),
        sa.Column("rate", sa.Numeric(6, 2), nullable=False),
        sa.Column("source", sa.String(16), nullable=False, server_default="cbr"),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("key_rates_daily")
