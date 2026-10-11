"""Полученные проценты — чтобы отделить кассу от бизнеса

Две колонки отчёта:
  interest_received          — проценты полученные за период, млн, из ОДДС;
  interest_received_in_ocf   — стоят ли они в операционной деятельности.

МСФО разрешает показывать полученные проценты и в операционной, и в
инвестиционной деятельности, и компании пользуются обоими вариантами: у
ЛУКОЙЛа они в операционной, у Интер РАО — в инвестиционной. Без отметки
раздела нельзя понять, сидят ли они в нашем свободном потоке. См.
`app/services/analysis/cash_income.py`.

Revision ID: m8b9c0d1e2f3
Revises: l7a8b9c0d1e2
Create Date: 2026-10-08
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "m8b9c0d1e2f3"
down_revision: Union[str, None] = "l7a8b9c0d1e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("financial_reports", sa.Column("interest_received", sa.Numeric(15, 3), nullable=True))
    op.add_column("financial_reports", sa.Column("interest_received_in_ocf", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("financial_reports", "interest_received_in_ocf")
    op.drop_column("financial_reports", "interest_received")
