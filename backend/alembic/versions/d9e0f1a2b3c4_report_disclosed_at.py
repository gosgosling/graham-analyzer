"""Фактическая дата раскрытия отчёта

До этого дата, с которой рынок знал отчёт, выводилась по правилу: годовой —
31 декабря + 120 дней, полугодие — 30 июня + 60 дней. У Северстали годовой
отчёт за 2025 год выходит раньше, и опорная по старому отчёту жила на графике
лишние месяцы, пока прибыль уже рухнула. Дата берётся из таблицы раскрытий
e-disclosure; где её нет, остаётся правило.

Revision ID: d9e0f1a2b3c4
Revises: c8d9e0f1a2b3
Create Date: 2026-09-30
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d9e0f1a2b3c4"
down_revision: Union[str, None] = "c8d9e0f1a2b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("financial_reports", sa.Column("disclosed_at", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("financial_reports", "disclosed_at")
