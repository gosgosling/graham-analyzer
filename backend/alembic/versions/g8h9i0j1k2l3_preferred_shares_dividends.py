"""preferred shares flag and dividends on prefs for adjusted NI / FCF

Revision ID: g8h9i0j1k2l3
Revises: f6a7b8c9d0e1
Create Date: 2026-05-06

Чекбокс «есть привилегированные акции» и сумма дивидендов по префам (млн валюты отчёта)
для расчёта скорректированной прибыли и FCF на обыкновенные акции.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "g8h9i0j1k2l3"
down_revision: Union[str, Sequence[str], None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "financial_reports",
        sa.Column(
            "has_preferred_shares",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "financial_reports",
        sa.Column(
            "preferred_share_dividends",
            sa.Numeric(15, 3),
            nullable=True,
            comment="Дивиденды по привилегированным акциям, млн валюты отчёта",
        ),
    )


def downgrade() -> None:
    op.drop_column("financial_reports", "preferred_share_dividends")
    op.drop_column("financial_reports", "has_preferred_shares")
