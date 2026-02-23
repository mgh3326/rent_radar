"""Business logic for listing searches."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from src.config.region_codes import is_valid_region_code
from src.db.repositories import fetch_listing_region_source_freshness, fetch_listings


class ListingService:
    """Service layer for MCP listing tools."""

    def __init__(self, session: AsyncSession) -> None:
        self._session: AsyncSession = session

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

        normalized_region_code = region_code.strip() if region_code else None

        rows = await fetch_listings(
            self._session,
            region_code=normalized_region_code,
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

    async def evaluate_crawl_status(
        self,
        *,
        region_code: str | None,
        stale_hours: int = 48,
        source: str = "zigbang",
    ) -> dict[str, object]:
        normalized_region_code = region_code.strip() if region_code else ""
        if not normalized_region_code:
            return {
                "source": source,
                "region_code": None,
                "evaluated": False,
                "needs_crawl": None,
                "reason": "no_region_filter",
                "last_seen_at": None,
                "stale_threshold_hours": stale_hours,
            }

        if not is_valid_region_code(normalized_region_code):
            return {
                "source": source,
                "region_code": normalized_region_code,
                "evaluated": False,
                "needs_crawl": None,
                "reason": "invalid_region_code",
                "last_seen_at": None,
                "stale_threshold_hours": stale_hours,
            }

        freshness = await fetch_listing_region_source_freshness(
            self._session,
            region_code=normalized_region_code,
            source=source,
        )

        if freshness.total_count == 0:
            return {
                "source": source,
                "region_code": normalized_region_code,
                "evaluated": True,
                "needs_crawl": True,
                "reason": "no_region_data",
                "last_seen_at": None,
                "stale_threshold_hours": stale_hours,
            }

        if freshness.last_seen_at is None:
            return {
                "source": source,
                "region_code": normalized_region_code,
                "evaluated": True,
                "needs_crawl": True,
                "reason": "stale_data",
                "last_seen_at": None,
                "stale_threshold_hours": stale_hours,
            }

        last_seen_at = freshness.last_seen_at
        if last_seen_at.tzinfo is None:
            last_seen_at = last_seen_at.replace(tzinfo=UTC)

        stale_threshold = datetime.now(UTC) - timedelta(hours=stale_hours)
        needs_crawl = last_seen_at < stale_threshold

        return {
            "source": source,
            "region_code": normalized_region_code,
            "evaluated": True,
            "needs_crawl": needs_crawl,
            "reason": "stale_data" if needs_crawl else "fresh_data",
            "last_seen_at": last_seen_at.isoformat(),
            "stale_threshold_hours": stale_hours,
        }
