"""Add trade_category to RealTrade model

Revision ID: a9a682cfdfed
Revises: 36508012aa82
Create Date: 2026-02-08 16:01:58.957330

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a9a682cfdfed"
down_revision: str | None = "36508012aa82"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add trade_category column with default value 'rent'
    op.add_column(
        "real_trades",
        sa.Column("trade_category", sa.String(), nullable=False, server_default="rent"),
    )

    # Drop old unique constraint (without trade_category)
    op.drop_constraint("uq_real_trades_identity", "real_trades", type_="unique")

    # Create new unique constraint (with trade_category)
    op.create_unique_constraint(
        "uq_real_trades_identity",
        "real_trades",
        [
            "property_type",
            "region_code",
            "dong",
            "apt_name",
            "area_m2",
            "floor",
            "contract_year",
            "contract_month",
            "contract_day",
            "rent_type",
            "trade_category",
        ],
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Drop new unique constraint (with trade_category)
    op.drop_constraint("uq_real_trades_identity", "real_trades", type_="unique")

    # Recreate old unique constraint (without trade_category)
    op.create_unique_constraint(
        "uq_real_trades_identity",
        "real_trades",
        [
            "property_type",
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

    # Drop trade_category column
    op.drop_column("real_trades", "trade_category")
