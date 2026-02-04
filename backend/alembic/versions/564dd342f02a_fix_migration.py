"""add financial_reports table

Revision ID: 564dd342f02a
Revises: 17dc655ef1c7
Create Date: 2026-02-04 21:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '564dd342f02a'
down_revision: Union[str, None] = '17dc655ef1c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Создание таблицы financial_reports
    op.create_table(
        'financial_reports',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('company_id', sa.Integer(), nullable=False),
        sa.Column('report_date', sa.Date(), nullable=False),
        sa.Column('price_per_share', sa.Numeric(15, 2), nullable=True),
        sa.Column('shares_outstanding', sa.Integer(), nullable=True),
        sa.Column('total_assets', sa.Numeric(15, 2), nullable=True),
        sa.Column('total_liabilities', sa.Numeric(15, 2), nullable=True),
        sa.Column('current_assets', sa.Numeric(15, 2), nullable=True),
        sa.Column('current_liabilities', sa.Numeric(15, 2), nullable=True),
        sa.Column('equity', sa.Numeric(15, 2), nullable=True),
        sa.Column('revenue', sa.Numeric(15, 2), nullable=True),
        sa.Column('net_income', sa.Numeric(15, 2), nullable=True),
        sa.Column('dividends_per_share', sa.Numeric(10, 4), nullable=True),
        sa.Column('dividends_paid', sa.Boolean(), nullable=True, server_default='false'),
        sa.Column('currency', sa.String(), nullable=False, server_default='RUB'),
        sa.Column('exchange_rate', sa.Numeric(10, 4), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_financial_reports_company_id'), 'financial_reports', ['company_id'], unique=False)
    op.create_index(op.f('ix_financial_reports_report_date'), 'financial_reports', ['report_date'], unique=False)
    
    # Добавление поля dividend_start_year в companies (если еще не добавлено)
    try:
        op.add_column('companies', sa.Column('dividend_start_year', sa.Integer(), nullable=True))
    except Exception:
        # Колонка уже существует, пропускаем
        pass


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_financial_reports_report_date'), table_name='financial_reports')
    op.drop_index(op.f('ix_financial_reports_company_id'), table_name='financial_reports')
    op.drop_table('financial_reports')
    try:
        op.drop_column('companies', 'dividend_start_year')
    except Exception:
        pass
