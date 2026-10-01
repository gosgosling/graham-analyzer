"""Неконтролирующая доля участия

`equity` в базе — капитал, приходящийся на акционеров материнской компании:
именно он стоит в знаменателе ROE и P/B, потому что миноритарий дочерней
структуры на эту прибыль прав не имеет. Из-за этого баланс в модели не
сходится ровно на долю миноритариев, и проверке аудита оставалось гадать по
величине разрыва: до десятой доли активов — «похоже на НКО», больше — дефект.

У холдингов порог срабатывал вхолостую. У Циана за 2024 год доля миноритариев
4 069 млн при капитале материнской 5 940 — разрыв 31%, и правильно введённый
отчёт объявлялся испорченным. Отдельное поле убирает догадку: там, где доля
записана, баланс проверяется точно.

Revision ID: c8d9e0f1a2b3
Revises: b7c8d9e0f1a2
Create Date: 2026-09-29
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c8d9e0f1a2b3"
down_revision: Union[str, None] = "b7c8d9e0f1a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "financial_reports",
        sa.Column("non_controlling_interest", sa.Numeric(20, 3), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("financial_reports", "non_controlling_interest")
