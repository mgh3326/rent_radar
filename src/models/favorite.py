"""User favorite listings table model."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class Favorite(Base):
    """User favorite listings."""

    __tablename__ = "favorites"
    __table_args__ = (
        UniqueConstraint("user_id", "listing_id", name="uq_favorites_user_listing"),
        Index("idx_favorites_user", "user_id"),
        Index("idx_favorites_listing", "listing_id"),
        Index("idx_favorites_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(nullable=False)
    listing_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("listings.id"), nullable=False
    )
    deposit_at_save: Mapped[int | None] = mapped_column(Integer, nullable=True)
    monthly_rent_at_save: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
