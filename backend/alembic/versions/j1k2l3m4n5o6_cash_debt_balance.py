"""Balance sheet: cash_and_equivalents and debt (for Net Debt)

Revision ID: j1k2l3m4n5o6
Revises: i0j1k2l3m4n5
Create Date: 2026-05-19

Net Debt = debt − cash_and_equivalents (computed in API, not stored).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "j1k2l3m4n5o6"
down_revision: Union[str, Sequence[str], None] = "i0j1k2l3m4n5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "financial_reports",
        sa.Column(
            "cash_and_equivalents",
            sa.Numeric(precision=15, scale=3),
            nullable=True,
            comment="Денежные средства и эквиваленты, млн валюты отчёта",
        ),
    )
    op.add_column(
        "financial_reports",
        sa.Column(
            "debt",
            sa.Numeric(precision=15, scale=3),
            nullable=True,
            comment="Долг (финансовые обязательства), млн валюты отчёта",
        ),
    )


def downgrade() -> None:
    op.drop_column("financial_reports", "debt")
    op.drop_column("financial_reports", "cash_and_equivalents")
