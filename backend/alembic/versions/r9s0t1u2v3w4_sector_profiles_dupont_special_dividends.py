"""Разовые дивиденды и данные для разложения ROE

Revision ID: r9s0t1u2v3w4
Revises: q8r9s0t1u2v3
Create Date: 2026-07-24
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "r9s0t1u2v3w4"
down_revision: Union[str, Sequence[str], None] = "q8r9s0t1u2v3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Разовая часть дивидендов: спецвыплаты, компенсация пропущенных лет,
    # распределение от продажи активов
    op.add_column(
        "financial_reports",
        sa.Column("special_dividends_per_share", sa.Numeric(10, 4), nullable=True),
    )
    op.add_column(
        "financial_reports",
        sa.Column("special_dividends_note", sa.String(256), nullable=True),
    )

    op.add_column(
        "multipliers",
        sa.Column("ltm_special_dividends_per_share", sa.Numeric(15, 4), nullable=True),
    )
    op.add_column(
        "multipliers",
        sa.Column("dividend_yield_regular", sa.Numeric(12, 4), nullable=True),
    )
    # Итого активы — нужны для разложения ROE (оборачиваемость и рычаг)
    op.add_column(
        "multipliers",
        sa.Column("total_assets", sa.Numeric(20, 2), nullable=True),
    )

    # До появления поля все выплаты считались регулярными — сохраняем
    # прежнее поведение для уже рассчитанных записей.
    op.execute(
        sa.text(
            "UPDATE multipliers SET dividend_yield_regular = dividend_yield "
            "WHERE dividend_yield IS NOT NULL"
        )
    )


def downgrade() -> None:
    op.drop_column("multipliers", "total_assets")
    op.drop_column("multipliers", "dividend_yield_regular")
    op.drop_column("multipliers", "ltm_special_dividends_per_share")
    op.drop_column("financial_reports", "special_dividends_note")
    op.drop_column("financial_reports", "special_dividends_per_share")
