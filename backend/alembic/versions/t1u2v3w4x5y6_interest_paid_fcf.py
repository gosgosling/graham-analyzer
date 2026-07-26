"""interest_paid для FCF (проценты уплаченные из financing)

Revision ID: t1u2v3w4x5y6
Revises: s0t1u2v3w4x5
Create Date: 2026-07-26

FCF = OCF − CAPEX − аренда − interest_paid
(interest_paid заполняется, если строка в финансовой деятельности ОДДС;
если проценты уже внутри OCF — поле null).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "t1u2v3w4x5y6"
down_revision: Union[str, Sequence[str], None] = "s0t1u2v3w4x5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "financial_reports",
        sa.Column("interest_paid", sa.Numeric(15, 3), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("financial_reports", "interest_paid")
