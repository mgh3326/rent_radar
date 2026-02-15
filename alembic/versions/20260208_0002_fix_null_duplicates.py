"""Fix NULL values in dong, apt_name, floor and resolve duplicate insertion issues.

Revision ID: 20260208_0002
Revises: 20260207_0001
Create Date: 2026-02-08 00:00:00
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260208_0002"
down_revision: str | None = "20260207_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""

    op.execute("UPDATE real_trades SET dong='' WHERE dong IS NULL")
    op.execute("UPDATE real_trades SET apt_name='' WHERE apt_name IS NULL")
    op.execute("UPDATE real_trades SET floor=0 WHERE floor IS NULL")

    op.execute("""
        DELETE FROM real_trades
        WHERE id NOT IN (
            SELECT MIN(id)
            FROM real_trades
            GROUP BY region_code, dong, apt_name, area_m2, floor,
                     contract_year, contract_month, contract_day, rent_type
        )
    """)

    op.alter_column("real_trades", "dong", nullable=False, server_default="")
    op.alter_column("real_trades", "apt_name", nullable=False, server_default="")
    op.alter_column("real_trades", "floor", nullable=False, server_default="0")

    op.drop_constraint("uq_real_trades_identity", "real_trades", type_="unique")
    op.create_unique_constraint(
        "uq_real_trades_identity",
        "real_trades",
        [
            "region_code",
            "dong",
            "apt_name",
            "area_m2",
            "floor",
            "contract_year",
            "contract_month",
            "contract_day",
            "rent_type",
        ],
        nulls_not_distinct=True,
    )


def downgrade() -> None:
    """Downgrade schema."""

    op.drop_constraint("uq_real_trades_identity", "real_trades", type_="unique")

    op.create_unique_constraint(
        "uq_real_trades_identity",
        "real_trades",
        [
            "region_code",
            "dong",
            "apt_name",
            "area_m2",
            "floor",
            "contract_year",
            "contract_month",
            "contract_day",
            "rent_type",
        ],
    )

    op.alter_column("real_trades", "dong", nullable=True, server_default=None)
    op.alter_column("real_trades", "apt_name", nullable=True, server_default=None)
    op.alter_column("real_trades", "floor", nullable=True, server_default=None)
