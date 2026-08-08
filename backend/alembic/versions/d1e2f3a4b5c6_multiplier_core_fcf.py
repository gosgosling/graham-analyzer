"""Поток ядра в кэше мультипликаторов

У гибрида (Яндекс, МОЕХ) часть операционного потока — прирост клиентских
депозитов. P/FCF, ND/FCF и FCF/Прибыль считаются от потока без него, и колонка
FCF в таблице истории должна показывать ту же величину, иначе рядом стоят
сырое число и очищенные от него отношения.

У остальных типов компаний поле остаётся пустым: там очищать нечего.

Revision ID: d1e2f3a4b5c6
Revises: c0d1e2f3a4b5
"""
from alembic import op
import sqlalchemy as sa

revision = "d1e2f3a4b5c6"
down_revision = "c0d1e2f3a4b5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "multipliers",
        sa.Column("ltm_core_fcf", sa.Numeric(20, 2), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("multipliers", "ltm_core_fcf")
