"""Price change tracking table model."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, func
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class PriceChange(Base):
    """Price change records for listings."""

    __tablename__ = "price_changes"
    __table_args__ = (
        Index("idx_price_changes_listing", "listing_id"),
        Index("idx_price_changes_date", "changed_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    listing_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("listings.id"), nullable=False
    )
    old_deposit: Mapped[int] = mapped_column(Integer, nullable=False)
    old_monthly_rent: Mapped[int] = mapped_column(Integer, nullable=False)
    new_deposit: Mapped[int] = mapped_column(Integer, nullable=False)
    new_monthly_rent: Mapped[int] = mapped_column(Integer, nullable=False)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
