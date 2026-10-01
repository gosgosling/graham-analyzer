"""Сравнительная колонка промежуточного отчёта

Прошлый год в том виде, в каком его показывает свежий отчёт. Нужна, когда
между полугодиями был пересчёт: строка прошлого полугодия хранит опубликованное
тогда, а для LTM по свежему отчёту берутся сопоставимые данные из его же
сравнительной колонки.

Revision ID: b7c8d9e0f1a2
Revises: a6b7c8d9e0f1
Create Date: 2026-09-26
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b7c8d9e0f1a2"
down_revision: Union[str, None] = "a6b7c8d9e0f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("financial_reports", sa.Column("comparative", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("financial_reports", "comparative")
