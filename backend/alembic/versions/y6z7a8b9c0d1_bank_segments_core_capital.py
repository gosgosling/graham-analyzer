"""Разбивка портфеля и депозитов, достаточность основного капитала

Розничные и корпоративные кредиты несут разный риск, розничные и
корпоративные средства — разную устойчивость фондирования. Один и тот же
CoR у розничного и корпоративного банка означает разное.

Достаточность основного капитала (Н1.1 / CET1) хранится отдельно от общей:
убытки поглощает ядро капитала, а общий норматив включает субординированные
займы, которые списываются не сразу.

Revision ID: y6z7a8b9c0d1
Revises: x5y6z7a8b9c0
Create Date: 2026-07-30
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "y6z7a8b9c0d1"
down_revision: Union[str, Sequence[str], None] = "x5y6z7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLUMNS: tuple[tuple[str, sa.types.TypeEngine], ...] = (
    ("loans_retail", sa.Numeric(15, 3)),
    ("loans_corporate", sa.Numeric(15, 3)),
    ("deposits_retail", sa.Numeric(15, 3)),
    ("deposits_corporate", sa.Numeric(15, 3)),
    ("capital_adequacy_core", sa.Numeric(6, 2)),
)


def upgrade() -> None:
    for name, type_ in _COLUMNS:
        op.add_column("financial_reports", sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    for name, _type in reversed(_COLUMNS):
        op.drop_column("financial_reports", name)
