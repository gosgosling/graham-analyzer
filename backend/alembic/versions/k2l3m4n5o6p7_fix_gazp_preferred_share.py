"""Сброс ошибочного is_preferred_share у GAZP и коротких тикеров *P

Revision ID: k2l3m4n5o6p7
Revises: j1k2l3m4n5o6
Create Date: 2026-06-08

Старая эвристика «тикер оканчивается на P» помечала GAZP (Газпром) как префы.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "k2l3m4n5o6p7"
down_revision: Union[str, Sequence[str], None] = "j1k2l3m4n5o6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE companies
           SET is_preferred_share = false
         WHERE is_preferred_share = true
           AND (
             UPPER(TRIM(ticker)) IN ('GAZP')
             OR (
               name NOT ILIKE '%привилег%'
               AND LENGTH(TRIM(ticker)) <= 4
               AND RIGHT(UPPER(TRIM(ticker)), 1) = 'P'
             )
           )
        """
    )


def downgrade() -> None:
    pass
