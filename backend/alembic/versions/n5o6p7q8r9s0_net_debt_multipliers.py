"""Net Debt и Net Debt/FCF в multipliers

Revision ID: n5o6p7q8r9s0
Revises: m4n5o6p7q8r9
Create Date: 2026-06-24
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "n5o6p7q8r9s0"
down_revision: Union[str, Sequence[str], None] = "m4n5o6p7q8r9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "multipliers",
        sa.Column("net_debt", sa.Numeric(20, 2), nullable=True),
    )
    op.add_column(
        "multipliers",
        sa.Column(
            "net_debt_to_fcf",
            sa.Numeric(12, 4),
            nullable=True,
            comment="Net Debt / LTM FCF (лет погашения)",
        ),
    )


def downgrade() -> None:
    op.drop_column("multipliers", "net_debt_to_fcf")
    op.drop_column("multipliers", "net_debt")
