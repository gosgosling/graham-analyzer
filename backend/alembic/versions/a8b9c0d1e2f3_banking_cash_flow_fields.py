"""Движение клиентских денег из ОДДС (встроенный финсервис)

Свободный поток компании со встроенным банком очищается от притока
клиентских денег. Считать его через разницу балансовых остатков неверно:
она включает секьюритизацию, списания и прекращение признания активов,
которые меняют баланс, но через денежный поток не проходят. У Яндекса за
2025 год расхождение — 77 млрд по ОДДС против 100 млрд по остаткам.

Поля общие для любой компании со встроенным финсервисом: Яндекс Банк,
Озон Банк и подобные. Значения переписываются из ОДДС со знаком.

Revision ID: a8b9c0d1e2f3
Revises: z7a8b9c0d1e2
Create Date: 2026-07-30
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a8b9c0d1e2f3"
down_revision: Union[str, Sequence[str], None] = "z7a8b9c0d1e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("financial_reports", sa.Column("cf_customer_deposits", sa.Numeric(15, 3), nullable=True))
    op.add_column("financial_reports", sa.Column("cf_customer_loans", sa.Numeric(15, 3), nullable=True))


def downgrade() -> None:
    op.drop_column("financial_reports", "cf_customer_loans")
    op.drop_column("financial_reports", "cf_customer_deposits")
