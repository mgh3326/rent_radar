"""add_property_type_to_unique_constraint

Revision ID: 36508012aa82
Revises: 20260208_0002
Create Date: 2026-02-08 13:10:20.414651

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "36508012aa82"
down_revision: str | None = "20260208_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""

    op.drop_constraint("uq_real_trades_identity", "real_trades", type_="unique")

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
