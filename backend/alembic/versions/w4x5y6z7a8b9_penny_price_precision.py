"""Шесть знаков в ценах и дивидендах на акцию (копеечные бумаги)

У ТГК-1 цена акции 0,004365 ₽, у ТГК-2 — 0,0042 ₽, дивиденды у таких эмитентов
измеряются долями копейки. При четырёх знаках после запятой цена теряла до
процента, а дивиденд округлялся в ноль вместе с доходностью. Округление здесь
всегда против нас: чем дешевле бумага, тем грубее ошибка.

Расширение точности безопасно в обе стороны: NUMERIC(18,6) вмещает всё, что
помещалось в NUMERIC(15,4). Обратная миграция округляет — данные дешёвых бумаг
при откате потеряются, поэтому downgrade возвращает прежние типы, но не
прежние значения.

Revision ID: w4x5y6z7a8b9
Revises: v3w4x5y6z7a8
Create Date: 2026-07-29
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "w4x5y6z7a8b9"
down_revision: Union[str, Sequence[str], None] = "v3w4x5y6z7a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (таблица, колонка, было, стало)
_COLUMNS: tuple[tuple[str, str, tuple[int, int], tuple[int, int]], ...] = (
    ("financial_reports", "price_per_share", (15, 4), (18, 6)),
    ("financial_reports", "price_at_filing", (15, 4), (18, 6)),
    ("financial_reports", "dividends_per_share", (10, 4), (14, 6)),
    ("financial_reports", "special_dividends_per_share", (10, 4), (14, 6)),
    ("companies", "current_price", (15, 4), (18, 6)),
    ("stock_prices", "price", (15, 4), (18, 6)),
    ("multipliers", "price_used", (15, 4), (18, 6)),
    ("multipliers", "ltm_dividends_per_share", (15, 4), (18, 6)),
    ("multipliers", "ltm_special_dividends_per_share", (15, 4), (18, 6)),
)


def upgrade() -> None:
    for table, column, _old, new in _COLUMNS:
        op.alter_column(
            table,
            column,
            type_=sa.Numeric(*new),
            existing_nullable=(table, column) != ("stock_prices", "price"),
        )


def downgrade() -> None:
    for table, column, old, _new in _COLUMNS:
        op.alter_column(
            table,
            column,
            type_=sa.Numeric(*old),
            existing_nullable=(table, column) != ("stock_prices", "price"),
        )
