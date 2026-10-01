"""Доходность 10-летних ОФЗ по бескупонной кривой

Безрисковая ставка в истории оценки считалась заменителем «ключевая + 1 п.п.»,
и после шоков он завышал её на три пункта: кривая переворачивается, ключевая
выше длинных облигаций. Теперь — фактическая доходность из кривой Мосбиржи.

Revision ID: a6b7c8d9e0f1
Revises: f5a6b7c8d9e0
Create Date: 2026-09-26
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a6b7c8d9e0f1"
down_revision: Union[str, None] = "f5a6b7c8d9e0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ofz_yields",
        sa.Column("date", sa.Date(), primary_key=True),
        sa.Column("y10", sa.Numeric(7, 3), nullable=False),
        sa.Column("source", sa.String(16), nullable=False, server_default="moex_zcyc"),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("ofz_yields")
