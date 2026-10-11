"""Депозиты и облигации — вторая часть кассы

Колонка `cash_investments`, млн: процентные вложения сверх денег и
эквивалентов — банковские депозиты дольше трёх месяцев и долговые бумаги.
Проценты с них уже вычитаются из прибыли (`interest_received`), и без самих
вложений касса учитывалась бы наполовину: доход убран, а деньги, которые его
приносят, к оценке не прибавлены. У Интер РАО на конец 2025 года это 183 млрд
векселей банков, облигаций и депозитов сверх 267 млрд денег. См. `app/services/analysis/cash_income.py`.

Revision ID: n9c0d1e2f3a4
Revises: m8b9c0d1e2f3
Create Date: 2026-10-09
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "n9c0d1e2f3a4"
down_revision: Union[str, None] = "m8b9c0d1e2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("financial_reports", sa.Column("cash_investments", sa.Numeric(15, 3), nullable=True))


def downgrade() -> None:
    op.drop_column("financial_reports", "cash_investments")
