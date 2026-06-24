"""Раздельные поля количества акций в financial_reports

Revision ID: m4n5o6p7q8r9
Revises: k2l3m4n5o6p7
Create Date: 2026-06-24

- shares_issued — размещённое (общее) количество
- shares_weighted_avg — средневзвешенное (для EPS)
- treasury_shares — казначейские
- shares_outstanding — явные «акции в обращении» (как было)

Откат: alembic downgrade m4n5o6p7q8r9
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "m4n5o6p7q8r9"
down_revision: Union[str, Sequence[str], None] = "k2l3m4n5o6p7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "financial_reports",
        sa.Column("shares_issued", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "financial_reports",
        sa.Column("shares_weighted_avg", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "financial_reports",
        sa.Column("treasury_shares", sa.BigInteger(), nullable=True),
    )

    # Старые записи: единственное поле трактовалось как «в обращении».
    # Дублируем в shares_issued для обязательного поля и сохраняем outstanding.
    op.execute(
        """
        UPDATE financial_reports
        SET shares_issued = shares_outstanding
        WHERE shares_outstanding IS NOT NULL
          AND shares_issued IS NULL
        """
    )


def downgrade() -> None:
    op.drop_column("financial_reports", "treasury_shares")
    op.drop_column("financial_reports", "shares_weighted_avg")
    op.drop_column("financial_reports", "shares_issued")
