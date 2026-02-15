"""add snapshot columns to favorites

Revision ID: 20260213_snapshot
Revises: 4c78e7bd1a29
Create Date: 2026-02-13

"""

from alembic import op
import sqlalchemy as sa


revision = "20260213_snapshot"
down_revision = "4c78e7bd1a29"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "favorites",
        sa.Column("deposit_at_save", sa.Integer(), nullable=True),
    )
    op.add_column(
        "favorites",
        sa.Column("monthly_rent_at_save", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("favorites", "monthly_rent_at_save")
    op.drop_column("favorites", "deposit_at_save")
