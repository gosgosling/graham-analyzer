"""Средняя ключевая ставка ЦБ по годам

Стоимость фондирования банка осмысленна только рядом со ставкой того же
периода: 12% при ставке 4% — катастрофа, при 19% — отличный результат.
Ряд по годам, а не текущее значение: отчёт 2022 года сравнивается со
средней за 2022-й.

Значения заполняются скриптом scripts/load_key_rates.py с сайта ЦБ;
здесь — стартовый набор, чтобы показатель работал сразу.

Revision ID: c0d1e2f3a4b5
Revises: b9c0d1e2f3a4
Create Date: 2026-07-31
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c0d1e2f3a4b5"
down_revision: Union[str, Sequence[str], None] = "b9c0d1e2f3a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    table = op.create_table(
        "key_rates",
        sa.Column("year", sa.Integer(), primary_key=True),
        sa.Column("avg_rate", sa.Numeric(6, 2), nullable=False),
        sa.Column("source", sa.String(16), nullable=False, server_default="cbr"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    # Стартовые значения — средние арифметические по дням действия ставки.
    # Обновляются скриптом; здесь нужны, чтобы спред считался сразу после миграции.
    op.bulk_insert(table, [
        {"year": 2021, "avg_rate": 5.83, "source": "cbr"},
        {"year": 2022, "avg_rate": 10.61, "source": "cbr"},
        {"year": 2023, "avg_rate": 9.94, "source": "cbr"},
        {"year": 2024, "avg_rate": 17.52, "source": "cbr"},
        {"year": 2025, "avg_rate": 19.13, "source": "cbr"},
    ])


def downgrade() -> None:
    op.drop_table("key_rates")
