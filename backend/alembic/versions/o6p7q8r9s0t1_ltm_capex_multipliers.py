"""LTM CAPEX в multipliers

Revision ID: o6p7q8r9s0t1
Revises: n5o6p7q8r9s0
Create Date: 2026-06-28
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "o6p7q8r9s0t1"
down_revision: Union[str, Sequence[str], None] = "n5o6p7q8r9s0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "multipliers",
        sa.Column(
            "ltm_capex",
            sa.Numeric(20, 2),
            nullable=True,
            comment="LTM CAPEX, млн ₽ (положительное число)",
        ),
    )


def downgrade() -> None:
    op.drop_column("multipliers", "ltm_capex")
