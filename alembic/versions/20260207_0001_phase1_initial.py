"""Phase 1 initial tables for listings and real trades.

Revision ID: 20260207_0001
Revises:
Create Date: 2026-02-07 18:35:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260207_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""

    op.create_table(
        "listings",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("source_id", sa.String(length=100), nullable=False),
        sa.Column("property_type", sa.String(length=20), nullable=False),
        sa.Column("rent_type", sa.String(length=10), nullable=False),
        sa.Column("deposit", sa.Integer(), nullable=False),
        sa.Column("monthly_rent", sa.Integer(), server_default="0", nullable=False),
        sa.Column("address", sa.Text(), nullable=False),
        sa.Column("dong", sa.String(length=50), nullable=True),
        sa.Column("detail_address", sa.Text(), nullable=True),
        sa.Column("area_m2", sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column("floor", sa.Integer(), nullable=True),
        sa.Column("total_floors", sa.Integer(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("latitude", sa.Numeric(precision=10, scale=7), nullable=True),
        sa.Column("longitude", sa.Numeric(precision=10, scale=7), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_listings"),
        sa.UniqueConstraint("source", "source_id", name="uq_listings_source_source_id"),
    )
    op.create_index(
        "idx_listings_region",
        "listings",
        ["dong", "property_type", "rent_type"],
        unique=False,
    )
    op.create_index("idx_listings_deposit", "listings", ["deposit"], unique=False)
    op.create_index("idx_listings_active", "listings", ["is_active"], unique=False)

    op.create_table(
        "real_trades",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("property_type", sa.String(length=20), nullable=False),
        sa.Column("rent_type", sa.String(length=10), nullable=False),
        sa.Column("region_code", sa.String(length=10), nullable=False),
        sa.Column("dong", sa.String(length=50), nullable=True),
        sa.Column("apt_name", sa.String(length=100), nullable=True),
        sa.Column("deposit", sa.Integer(), nullable=False),
        sa.Column("monthly_rent", sa.Integer(), server_default="0", nullable=False),
        sa.Column("area_m2", sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column("floor", sa.Integer(), nullable=True),
        sa.Column("contract_year", sa.Integer(), nullable=False),
        sa.Column("contract_month", sa.Integer(), nullable=False),
        sa.Column("contract_day", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_real_trades"),
        sa.UniqueConstraint(
            "region_code",
            "dong",
            "apt_name",
            "area_m2",
            "floor",
            "contract_year",
            "contract_month",
            "contract_day",
            "rent_type",
            name="uq_real_trades_identity",
        ),
    )
    op.create_index(
        "idx_real_trades_region", "real_trades", ["region_code", "dong"], unique=False
    )
    op.create_index(
        "idx_real_trades_date",
        "real_trades",
        ["contract_year", "contract_month"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""

    op.drop_index("idx_real_trades_date", table_name="real_trades")
    op.drop_index("idx_real_trades_region", table_name="real_trades")
    op.drop_table("real_trades")

    op.drop_index("idx_listings_active", table_name="listings")
    op.drop_index("idx_listings_deposit", table_name="listings")
    op.drop_index("idx_listings_region", table_name="listings")
    op.drop_table("listings")
