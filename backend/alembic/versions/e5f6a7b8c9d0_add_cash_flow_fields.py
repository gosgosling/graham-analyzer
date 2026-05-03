"""add_cash_flow_fields

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-05-03

Добавляет поля ОДДС (operating_cash_flow, capex) в таблицу financial_reports
и поля FCF-мультипликаторов (ltm_fcf, ltm_operating_cash_flow, price_to_fcf,
fcf_to_net_income) в таблицу multipliers.
"""

from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op

revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, Sequence[str], None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── financial_reports: поля денежных потоков ──────────────────────────────
    op.add_column(
        'financial_reports',
        sa.Column('operating_cash_flow', sa.Numeric(15, 3), nullable=True,
                  comment='Операционный денежный поток, млн валюты'),
    )
    op.add_column(
        'financial_reports',
        sa.Column('capex', sa.Numeric(15, 3), nullable=True,
                  comment='CAPEX (положит. число), млн валюты'),
    )

    # ── multipliers: LTM FCF и производные мультипликаторы ───────────────────
    op.add_column(
        'multipliers',
        sa.Column('ltm_fcf', sa.Numeric(20, 2), nullable=True,
                  comment='LTM FCF = OCF - CAPEX, млн рублей'),
    )
    op.add_column(
        'multipliers',
        sa.Column('ltm_operating_cash_flow', sa.Numeric(20, 2), nullable=True,
                  comment='LTM операционный поток, млн рублей'),
    )
    op.add_column(
        'multipliers',
        sa.Column('price_to_fcf', sa.Numeric(12, 4), nullable=True,
                  comment='P/FCF = Market Cap / LTM FCF (NULL для банков и FCF <= 0)'),
    )
    op.add_column(
        'multipliers',
        sa.Column('fcf_to_net_income', sa.Numeric(12, 4), nullable=True,
                  comment='FCF/NI = LTM FCF / LTM Net Income * 100%, детектор качества прибыли'),
    )


def downgrade() -> None:
    op.drop_column('multipliers', 'fcf_to_net_income')
    op.drop_column('multipliers', 'price_to_fcf')
    op.drop_column('multipliers', 'ltm_operating_cash_flow')
    op.drop_column('multipliers', 'ltm_fcf')
    op.drop_column('financial_reports', 'capex')
    op.drop_column('financial_reports', 'operating_cash_flow')
