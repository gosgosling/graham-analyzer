"""Банковские поля отчёта: портфель, качество активов, фондирование, капитал

Без них по банку считались только ROE, P/B и Cost-to-Income — то есть
доходность и цена, но не риск. Стоимость риска требует кредитного портфеля,
качество активов — обесцененных кредитов и накопленного резерва, устойчивость
фондирования — средств клиентов, запас по капиталу — Н1.0 и RWA.

Все суммы — в миллионах валюты отчёта, как остальные показатели.
Расходные величины (резерв, процентные расходы) хранятся положительными
числами: знак задаётся формулой, а не вводом.

Revision ID: x5y6z7a8b9c0
Revises: w4x5y6z7a8b9
Create Date: 2026-07-30
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "x5y6z7a8b9c0"
down_revision: Union[str, Sequence[str], None] = "w4x5y6z7a8b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (колонка, тип) — все nullable: у небанковских отчётов они пустые,
# у банковских заполняются по мере разбора примечаний.
_COLUMNS: tuple[tuple[str, sa.types.TypeEngine], ...] = (
    ("interest_income", sa.Numeric(15, 3)),
    ("interest_expense", sa.Numeric(15, 3)),
    ("gross_loans", sa.Numeric(15, 3)),
    ("loan_loss_allowance", sa.Numeric(15, 3)),
    ("npl_loans", sa.Numeric(15, 3)),
    ("customer_deposits", sa.Numeric(15, 3)),
    ("risk_weighted_assets", sa.Numeric(15, 3)),
    ("capital_adequacy_ratio", sa.Numeric(6, 2)),
)


def upgrade() -> None:
    for name, type_ in _COLUMNS:
        op.add_column("financial_reports", sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    for name, _type in reversed(_COLUMNS):
        op.drop_column("financial_reports", name)
