"""is_preferred_share on companies (для тикеров привилегированных акций)

Revision ID: h9i0j1k2l3m4
Revises: g8h9i0j1k2l3
Create Date: 2026-05-17

Флаг отмечает, что инструмент (тикер) — это привилегированные акции
(TRNFP, BANEP, SBERP). Для таких тикеров поле dividends_per_share в
отчётах хранит дивиденд по префам, и для них:
  * Div. Yield считается по этим дивидендам и не «штрафуется» меткой
    «нет выплат по обыкновенным»;
  * чекбокс «Есть привилегированные акции» в форме скрывается
    (мы и так смотрим на сами префы);
  * корректировка чистой прибыли / FCF на префы не применяется.

Автодетект по суффиксу «P» делаем здесь же — для всех существующих
тикеров вида ...P длиной ≥ 2 ставим True. Дальше значение можно
переопределить вручную через PATCH /companies/{id}.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "h9i0j1k2l3m4"
down_revision: Union[str, Sequence[str], None] = "g8h9i0j1k2l3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "companies",
        sa.Column(
            "is_preferred_share",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    # Бэкфилл: тикеры, оканчивающиеся на «P» (BANEP, TRNFP, SBERP, NKNCP, …).
    # Не трогаем односимвольные «P» и тикеры с дефисом перед P (на всякий случай).
    op.execute(
        """
        UPDATE companies
           SET is_preferred_share = true
         WHERE ticker IS NOT NULL
           AND length(ticker) >= 2
           AND right(ticker, 1) = 'P'
        """
    )


def downgrade() -> None:
    op.drop_column("companies", "is_preferred_share")
