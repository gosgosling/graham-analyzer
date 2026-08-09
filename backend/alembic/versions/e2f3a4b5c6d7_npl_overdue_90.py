"""Просрочка свыше 90 дней отдельным полем

Раньше в npl_loans клали то Стадию 3, то просрочку 90+ — в зависимости от
того, что раскрыл эмитент. Это две разные величины: Стадия 3 включает
реструктуризации, по которым платежи идут, и у ВТБ за 2025 год она вдвое
больше просрочки (1 610 против 866 млрд). Ряд из смеси двух определений даёт
скачки, которых не было в реальности.

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
"""
from alembic import op
import sqlalchemy as sa

revision = "e2f3a4b5c6d7"
down_revision = "d1e2f3a4b5c6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "financial_reports",
        sa.Column("npl_overdue_90", sa.Numeric(15, 3), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("financial_reports", "npl_overdue_90")
