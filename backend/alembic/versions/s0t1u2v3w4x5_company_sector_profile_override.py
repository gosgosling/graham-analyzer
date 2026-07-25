"""Ручное закрепление отраслевого профиля за компанией

Revision ID: s0t1u2v3w4x5
Revises: r9s0t1u2v3w4
Create Date: 2026-07-24
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "s0t1u2v3w4x5"
down_revision: Union[str, Sequence[str], None] = "r9s0t1u2v3w4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Сектор из T-Invest слишком крупный: «consumer» объединяет продуктовые
    # сети и магазины электроники, у которых нормы по ликвидности и долгу
    # различаются в разы. Поле позволяет аналитику закрепить нужный профиль.
    op.add_column(
        "companies",
        sa.Column("sector_profile_key", sa.String(32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("companies", "sector_profile_key")
