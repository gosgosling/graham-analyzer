"""Ссылки из писем: новый адрес при смене почты

Revision ID: k6f7a8b9c0d1
Revises: j5e6f7a8b9c0
Create Date: 2026-10-01
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "k6f7a8b9c0d1"
down_revision: Union[str, None] = "j5e6f7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("auth_tokens", sa.Column("new_email", sa.String(length=254), nullable=True))


def downgrade() -> None:
    op.drop_column("auth_tokens", "new_email")
