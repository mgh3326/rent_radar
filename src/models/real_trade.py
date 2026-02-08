"""Real trade price table model."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Index, Integer, Numeric, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class RealTrade(Base):
    """Official real trade records from public API."""

    __tablename__ = "real_trades"
    __table_args__ = (
        UniqueConstraint(
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
            name="uq_real_trades_identity",
        ),
        Index("idx_real_trades_region", "region_code", "dong"),
        Index("idx_real_trades_date", "contract_year", "contract_month"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    property_type: Mapped[str] = mapped_column(nullable=False)
    rent_type: Mapped[str] = mapped_column(nullable=False)
    trade_category: Mapped[str] = mapped_column(nullable=False, server_default="rent")
    region_code: Mapped[str] = mapped_column(nullable=False)
    dong: Mapped[str] = mapped_column(nullable=False, server_default="")
    apt_name: Mapped[str] = mapped_column(nullable=False, server_default="")
    deposit: Mapped[int] = mapped_column(Integer, nullable=False)
    monthly_rent: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    area_m2: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    floor: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    contract_year: Mapped[int] = mapped_column(Integer, nullable=False)
    contract_month: Mapped[int] = mapped_column(Integer, nullable=False)
    contract_day: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
