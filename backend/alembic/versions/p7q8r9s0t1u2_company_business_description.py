"""Описание компании (ручное / LLM)

Revision ID: p7q8r9s0t1u2
Revises: o6p7q8r9s0t1
Create Date: 2026-07-03
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "p7q8r9s0t1u2"
down_revision: Union[str, Sequence[str], None] = "o6p7q8r9s0t1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "companies",
        sa.Column(
            "business_description",
            sa.Text(),
            nullable=True,
            comment="Описание деятельности компании",
        ),
    )
    op.add_column(
        "companies",
        sa.Column(
            "business_description_source",
            sa.String(16),
            nullable=True,
            comment="Источник описания: manual | llm",
        ),
    )
    op.add_column(
        "companies",
        sa.Column(
            "business_description_updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Когда описание последний раз обновлялось",
        ),
    )


def downgrade() -> None:
    op.drop_column("companies", "business_description_updated_at")
    op.drop_column("companies", "business_description_source")
    op.drop_column("companies", "business_description")
