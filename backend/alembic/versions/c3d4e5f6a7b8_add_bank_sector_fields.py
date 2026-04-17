"""add bank sector fields to financial_reports and multipliers

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-04-17

Добавляет поддержку банковского сектора:
- financial_reports.report_type      — тип отрасли: general / bank
- financial_reports.net_interest_income  — чистые процентные доходы (NII), млн
- financial_reports.fee_commission_income — чистые комиссионные доходы, млн
- financial_reports.operating_expenses   — операционные расходы (до резервов), млн
- financial_reports.provisions           — резервы под обесценение кредитов, млн
- multipliers.cost_to_income             — Cost-to-Income ratio (%) для банков
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── financial_reports ────────────────────────────────────────────────────
    op.add_column(
        'financial_reports',
        sa.Column(
            'report_type',
            sa.String(length=20),
            nullable=False,
            server_default='general',
        ),
    )
    op.create_index(
        'ix_financial_reports_report_type',
        'financial_reports',
        ['report_type'],
    )

    op.add_column(
        'financial_reports',
        sa.Column('net_interest_income', sa.Numeric(precision=15, scale=3), nullable=True),
    )
    op.add_column(
        'financial_reports',
        sa.Column('fee_commission_income', sa.Numeric(precision=15, scale=3), nullable=True),
    )
    op.add_column(
        'financial_reports',
        sa.Column('operating_expenses', sa.Numeric(precision=15, scale=3), nullable=True),
    )
    op.add_column(
        'financial_reports',
        sa.Column('provisions', sa.Numeric(precision=15, scale=3), nullable=True),
    )

    # ── multipliers ──────────────────────────────────────────────────────────
    op.add_column(
        'multipliers',
        sa.Column('cost_to_income', sa.Numeric(precision=12, scale=4), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('multipliers', 'cost_to_income')

    op.drop_column('financial_reports', 'provisions')
    op.drop_column('financial_reports', 'operating_expenses')
    op.drop_column('financial_reports', 'fee_commission_income')
    op.drop_column('financial_reports', 'net_interest_income')
    op.drop_index('ix_financial_reports_report_type', table_name='financial_reports')
    op.drop_column('financial_reports', 'report_type')
