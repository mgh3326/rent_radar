"""Listing table model."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class Listing(Base):
    """Rental listing collected from external sources."""

    __tablename__ = "listings"
    __table_args__ = (
        UniqueConstraint("source", "source_id", name="uq_listings_source_source_id"),
        Index("idx_listings_region", "dong", "property_type", "rent_type"),
        Index("idx_listings_deposit", "deposit"),
        Index("idx_listings_active", "is_active"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(nullable=False)
    source_id: Mapped[str] = mapped_column(nullable=False)
    property_type: Mapped[str] = mapped_column(nullable=False)
    rent_type: Mapped[str] = mapped_column(nullable=False)
    deposit: Mapped[int] = mapped_column(Integer, nullable=False)
    monthly_rent: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    address: Mapped[str] = mapped_column(Text, nullable=False)
    dong: Mapped[str | None] = mapped_column(nullable=True)
    detail_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    area_m2: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    floor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_floors: Mapped[int | None] = mapped_column(Integer, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
