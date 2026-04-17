"""add AI extraction and analyst verification fields to financial_reports

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-04-17

Добавляет поля для поддержки автоматического извлечения данных из PDF
нейросетью и ручной верификации финансовым аналитиком:

- financial_reports.auto_extracted       — отчёт создан AI-парсером
- financial_reports.verified_by_analyst  — отчёт проверен аналитиком
- financial_reports.extraction_notes     — пометки AI о неуверенных полях
- financial_reports.extraction_model     — идентификатор использованной модели
- financial_reports.source_pdf_path      — путь к исходному PDF
- financial_reports.verified_at          — дата/время верификации
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, Sequence[str], None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # auto_extracted: существующие отчёты заведены вручную → False
    op.add_column(
        'financial_reports',
        sa.Column(
            'auto_extracted',
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_index(
        'ix_financial_reports_auto_extracted',
        'financial_reports',
        ['auto_extracted'],
    )

    # verified_by_analyst: существующие отчёты заведены пользователем → True
    op.add_column(
        'financial_reports',
        sa.Column(
            'verified_by_analyst',
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.create_index(
        'ix_financial_reports_verified_by_analyst',
        'financial_reports',
        ['verified_by_analyst'],
    )

    op.add_column(
        'financial_reports',
        sa.Column('extraction_notes', sa.Text(), nullable=True),
    )
    op.add_column(
        'financial_reports',
        sa.Column('extraction_model', sa.String(length=100), nullable=True),
    )
    op.add_column(
        'financial_reports',
        sa.Column('source_pdf_path', sa.String(length=512), nullable=True),
    )
    op.add_column(
        'financial_reports',
        sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('financial_reports', 'verified_at')
    op.drop_column('financial_reports', 'source_pdf_path')
    op.drop_column('financial_reports', 'extraction_model')
    op.drop_column('financial_reports', 'extraction_notes')
    op.drop_index(
        'ix_financial_reports_verified_by_analyst',
        table_name='financial_reports',
    )
    op.drop_column('financial_reports', 'verified_by_analyst')
    op.drop_index(
        'ix_financial_reports_auto_extracted',
        table_name='financial_reports',
    )
    op.drop_column('financial_reports', 'auto_extracted')
