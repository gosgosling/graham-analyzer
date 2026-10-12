"""Источник текущей цены и время котировки

Колонки `price_source` («tinvest» или «moex») и `price_quoted_at` у компании.
Текущая цена теперь приходит из двух мест: T-Invest, а при его недоступности —
Мосбиржа, у которой без авторизации котировка запаздывает на 15 минут.
Читателю надо видеть, откуда цена и насколько она свежая: оценка с ценой
недельной давности выглядит так же, как сегодняшняя, если об этом молчать.

Revision ID: o0d1e2f3a4b5
Revises: n9c0d1e2f3a4
Create Date: 2026-10-12
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "o0d1e2f3a4b5"
down_revision: Union[str, None] = "n9c0d1e2f3a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("companies", sa.Column("price_source", sa.String(16), nullable=True))
    op.add_column("companies", sa.Column("price_quoted_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("companies", "price_quoted_at")
    op.drop_column("companies", "price_source")
