"""FCF/NI: проценты → безразмерное соотношение

Revision ID: q8r9s0t1u2v3
Revises: p7q8r9s0t1u2
Create Date: 2026-07-03
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "q8r9s0t1u2v3"
down_revision: Union[str, Sequence[str], None] = "p7q8r9s0t1u2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Раньше хранилось как FCF/NI × 100 (85 = 85%). Переводим в соотношение (0.85).
    op.execute(
        sa.text(
            "UPDATE multipliers SET fcf_to_net_income = fcf_to_net_income / 100 "
            "WHERE fcf_to_net_income IS NOT NULL"
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE multipliers SET fcf_to_net_income = fcf_to_net_income * 100 "
            "WHERE fcf_to_net_income IS NOT NULL"
        )
    )
