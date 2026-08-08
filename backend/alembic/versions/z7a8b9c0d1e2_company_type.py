"""Тип компании: метод анализа отдельно от отрасли

Набор метрик выводился из сектора: всё, что T-Invest помечает как
`financial`, получало банковский отчёт и норматив достаточности капитала.
Так АФК Система и SFI — холдинги без банковского бизнеса — оказались
«банками» с Н1 и стоимостью риска.

Отрасль (sector) отвечает, с кем сравнивать. Тип (company_type) — как
считать. Значение по умолчанию `industrial`: новая компания не должна молча
получать чужие метрики.

Revision ID: z7a8b9c0d1e2
Revises: y6z7a8b9c0d1
Create Date: 2026-07-30
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "z7a8b9c0d1e2"
down_revision: Union[str, Sequence[str], None] = "y6z7a8b9c0d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Разовая раскладка по тикерам: дальше тип правится вручную в карточке.
_LENDERS = (
    "SBER", "SBERP", "VTBR", "BSPB", "BSPBP", "CBOM", "MBNK", "T",
    "SVCB", "DOMRF", "CARM", "ZAYM", "MGKL",
)
_INSURANCE = ("RENI",)
_HOLDINGS = ("AFKS", "SFIN")
_HYBRIDS = ("MOEX", "SPBE", "YDEX", "FRHC")


def upgrade() -> None:
    op.add_column(
        "companies",
        sa.Column(
            "company_type", sa.String(16), nullable=False, server_default="industrial"
        ),
    )
    op.create_index("ix_companies_company_type", "companies", ["company_type"])

    for value, tickers in (
        ("lender", _LENDERS),
        ("insurance", _INSURANCE),
        ("holding", _HOLDINGS),
        ("hybrid", _HYBRIDS),
    ):
        op.execute(
            sa.text("UPDATE companies SET company_type = :v WHERE ticker IN :t")
            .bindparams(sa.bindparam("t", expanding=True))
            .bindparams(v=value, t=list(tickers))
        )

    # Отчёты, которым сектор `financial` уже проставил банковский набор,
    # хотя компания не кредитор: холдинги, страховщик, биржи.
    op.execute(
        """
        UPDATE financial_reports r
        SET report_type = 'general'
        FROM companies c
        WHERE r.company_id = c.id
          AND c.company_type <> 'lender'
          AND r.report_type = 'bank'
        """
    )
    op.execute(
        """
        UPDATE financial_reports r
        SET report_type = 'bank'
        FROM companies c
        WHERE r.company_id = c.id
          AND c.company_type = 'lender'
          AND r.report_type <> 'bank'
        """
    )


def downgrade() -> None:
    op.drop_index("ix_companies_company_type", table_name="companies")
    op.drop_column("companies", "company_type")
