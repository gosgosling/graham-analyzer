"""intangible_assets — НМА отдельно от гудвила

Гудвил и прочие нематериальные активы ведут себя по-разному, поэтому
хранятся разными полями. Гудвил — след цены за прошлые покупки, списывается
разом. НМА — купленные лицензии, софт, права: часть из них настоящие
средства производства, часть (условные льготы, отложенные права) держится
на выполнении будущих условий. Отличить одно от другого построчно модель не
может, поэтому в multipliers ложится доля всего нематериального в капитале —
чтобы видеть, какая часть балансовой стоимости не твёрдая.

pb_tangible при этом намеренно НЕ меняется: он остаётся «капитал минус
гудвил», как требует гл. 15 у Грэма (см. screen_axes._tangible_pb).

Revision ID: e4f5a6b7c8d9
Revises: d3e4f5a6b7c8
"""
from alembic import op
import sqlalchemy as sa

revision = "e4f5a6b7c8d9"
down_revision = "d3e4f5a6b7c8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "financial_reports",
        sa.Column("intangible_assets", sa.Numeric(15, 3), nullable=True),
    )
    op.add_column(
        "multipliers",
        sa.Column("intangible_assets", sa.Numeric(20, 2), nullable=True),
    )
    op.add_column(
        "multipliers",
        sa.Column("intangibles_to_equity", sa.Numeric(8, 2), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("multipliers", "intangibles_to_equity")
    op.drop_column("multipliers", "intangible_assets")
    op.drop_column("financial_reports", "intangible_assets")
