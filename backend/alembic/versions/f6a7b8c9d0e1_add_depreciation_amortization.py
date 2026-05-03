"""add depreciation_amortization to financial_reports

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-05-03

Амортизация и износ (D&A), млн — для диагностики CAPEX vs амортизация;
не участвует в расчёте мультипликаторов (отдельный модуль анализа позже).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, Sequence[str], None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "financial_reports",
        sa.Column(
            "depreciation_amortization",
            sa.Numeric(15, 3),
            nullable=True,
            comment="Амортизация и износ (D&A), млн — сопоставление с CAPEX",
        ),
    )


def downgrade() -> None:
    op.drop_column("financial_reports", "depreciation_amortization")
