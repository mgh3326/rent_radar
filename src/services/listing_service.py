"""Business logic for listing searches."""

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from src.db.repositories import fetch_listings


class ListingService:
    """Service layer for MCP listing tools."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def search_listings(
        self,
        *,
        region_code: str | None = None,
        dong: str | None = None,
        property_type: str | None = None,
        rent_type: str | None = None,
        min_deposit: int | None = None,
        max_deposit: int | None = None,
        min_monthly_rent: int | None = None,
        max_monthly_rent: int | None = None,
        min_area: Decimal | None = None,
        max_area: Decimal | None = None,
        min_floor: int | None = None,
        max_floor: int | None = None,
        is_active: bool | None = None,
        limit: int = 50,
    ) -> list[dict[str, object]]:
        """Search listings with optional filters."""

        rows = await fetch_listings(
            self._session,
            region_code=region_code,
            dong=dong,
            property_type=property_type,
            rent_type=rent_type,
            min_deposit=min_deposit,
            max_deposit=max_deposit,
            min_monthly_rent=min_monthly_rent,
            max_monthly_rent=max_monthly_rent,
            min_area=min_area,
            max_area=max_area,
            min_floor=min_floor,
            max_floor=max_floor,
            is_active=is_active,
            limit=limit,
        )

        return [
            {
                "id": row.id,
                "source": row.source,
                "source_id": row.source_id,
                "property_type": row.property_type,
                "rent_type": row.rent_type,
                "deposit": row.deposit,
                "monthly_rent": row.monthly_rent,
                "address": row.address,
                "dong": row.dong,
                "detail_address": row.detail_address,
                "area_m2": float(row.area_m2) if row.area_m2 is not None else None,
                "floor": row.floor,
                "total_floors": row.total_floors,
                "description": row.description,
                "latitude": float(row.latitude) if row.latitude is not None else None,
                "longitude": float(row.longitude)
                if row.longitude is not None
                else None,
                "is_active": row.is_active,
                "first_seen_at": row.first_seen_at.isoformat()
                if row.first_seen_at
                else None,
                "last_seen_at": row.last_seen_at.isoformat()
                if row.last_seen_at
                else None,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            }
            for row in rows
        ]
