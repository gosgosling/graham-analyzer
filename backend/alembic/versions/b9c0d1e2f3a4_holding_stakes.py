"""Доли холдинга, долг корпцентра, покрытие процентов

Холдинг оценивается не по консолидированной отчётности, а по сумме долей
за вычетом долга корпоративного центра. Публичные доли считаются по
карточкам дочек, которые уже есть в базе; непубличные оцениваются вручную.

Заодно два поля отчёта — операционная прибыль и финансовые расходы: их
отношение (покрытие процентов) у Грэма один из тестов устойчивости, а для
холдинга — единственный показатель его собственной жизнеспособности.

Revision ID: b9c0d1e2f3a4
Revises: a8b9c0d1e2f3
Create Date: 2026-07-31
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b9c0d1e2f3a4"
down_revision: Union[str, Sequence[str], None] = "a8b9c0d1e2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "holding_stakes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "holding_company_id",
            sa.Integer(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "subsidiary_company_id",
            sa.Integer(),
            sa.ForeignKey("companies.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("share_pct", sa.Numeric(6, 3), nullable=False),
        sa.Column("manual_valuation", sa.Numeric(15, 3), nullable=True),
        sa.Column("valuation_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_holding_stakes_holding", "holding_stakes", ["holding_company_id"])
    op.create_index("ix_holding_stakes_subsidiary", "holding_stakes", ["subsidiary_company_id"])

    op.add_column("companies", sa.Column("corporate_center_net_debt", sa.Numeric(15, 3), nullable=True))
    op.add_column("financial_reports", sa.Column("operating_profit", sa.Numeric(15, 3), nullable=True))
    op.add_column("financial_reports", sa.Column("finance_costs", sa.Numeric(15, 3), nullable=True))


def downgrade() -> None:
    op.drop_column("financial_reports", "finance_costs")
    op.drop_column("financial_reports", "operating_profit")
    op.drop_column("companies", "corporate_center_net_debt")
    op.drop_index("ix_holding_stakes_subsidiary", table_name="holding_stakes")
    op.drop_index("ix_holding_stakes_holding", table_name="holding_stakes")
    op.drop_table("holding_stakes")
