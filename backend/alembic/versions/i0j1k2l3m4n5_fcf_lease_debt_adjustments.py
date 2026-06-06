"""FCF adjustments: lease principal/interest and debt principal on cash flow

Revision ID: i0j1k2l3m4n5
Revises: h9i0j1k2l3m4
Create Date: 2026-05-19

Опциональные корректировки FCF (млн валюты отчёта, положительные оттоки):
  lease_principal — тело аренды (IFRS 16)
  lease_interest — проценты по аренде
  debt_principal — выплаты по долговым ЦБ (тело долга)

FCF = OCF − CAPEX − lease_principal − lease_interest − debt_principal
(последние три слагаемые = 0, если не заполнены).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "i0j1k2l3m4n5"
down_revision: Union[str, Sequence[str], None] = "h9i0j1k2l3m4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "financial_reports",
        sa.Column(
            "lease_principal",
            sa.Numeric(15, 3),
            nullable=True,
            comment="Тело аренды (IFRS 16), млн валюты, положит. отток",
        ),
    )
    op.add_column(
        "financial_reports",
        sa.Column(
            "lease_interest",
            sa.Numeric(15, 3),
            nullable=True,
            comment="Проценты по аренде, млн валюты, положит. отток",
        ),
    )
    op.add_column(
        "financial_reports",
        sa.Column(
            "debt_principal",
            sa.Numeric(15, 3),
            nullable=True,
            comment="Выплаты по долговым ЦБ (тело), млн валюты, положит. отток",
        ),
    )


def downgrade() -> None:
    op.drop_column("financial_reports", "debt_principal")
    op.drop_column("financial_reports", "lease_interest")
    op.drop_column("financial_reports", "lease_principal")
