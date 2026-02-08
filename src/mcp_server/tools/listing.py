"""MCP tools for rental listing search."""

from decimal import Decimal

from mcp.server.fastmcp import FastMCP

from src.db.session import session_context
from src.services.listing_service import ListingService


def register_listing_tools(mcp: FastMCP) -> None:
    """Register listing-related tools on a FastMCP server."""

    @mcp.tool(name="search_rent")
    async def search_rent(
        region_code: str | None = None,
        dong: str | None = None,
        property_type: str | None = None,
        rent_type: str | None = None,
        min_deposit: int | None = None,
        max_deposit: int | None = None,
        min_monthly_rent: int | None = None,
        max_monthly_rent: int | None = None,
        min_area: float | None = None,
        max_area: float | None = None,
        min_floor: int | None = None,
        max_floor: int | None = None,
        limit: int = 50,
    ) -> dict[str, object]:
        """Search rental listings with optional filters.

        Args:
            region_code: 5-digit region code (e.g., 11110 for Jongno-gu)
            dong: Legal dong name (optional, filters by dong name)
            property_type: Property type - "apt" (아파트), "villa" (연립다세대), "officetel" (오피스텔)
            rent_type: Rent type - "jeonse" (전세), "monthly" (월세)
            min_deposit: Minimum deposit amount (in ten thousand won)
            max_deposit: Maximum deposit amount (in ten thousand won)
            min_monthly_rent: Minimum monthly rent (in ten thousand won)
            max_monthly_rent: Maximum monthly rent (in ten thousand won)
            min_area: Minimum area in square meters
            max_area: Maximum area in square meters
            min_floor: Minimum floor number
            max_floor: Maximum floor number
            limit: Maximum number of results to return (default: 50)
        """

        async with session_context() as session:
            service = ListingService(session)
            results = await service.search_listings(
                region_code=region_code,
                dong=dong,
                property_type=property_type,
                rent_type=rent_type,
                min_deposit=min_deposit,
                max_deposit=max_deposit,
                min_monthly_rent=min_monthly_rent,
                max_monthly_rent=max_monthly_rent,
                min_area=Decimal(str(min_area)) if min_area is not None else None,
                max_area=Decimal(str(max_area)) if max_area is not None else None,
                min_floor=min_floor,
                max_floor=max_floor,
                is_active=True,
                limit=limit,
            )
        return {
            "query": {
                "region_code": region_code,
                "dong": dong,
                "property_type": property_type,
                "rent_type": rent_type,
                "min_deposit": min_deposit,
                "max_deposit": max_deposit,
                "min_monthly_rent": min_monthly_rent,
                "max_monthly_rent": max_monthly_rent,
                "min_area": min_area,
                "max_area": max_area,
                "min_floor": min_floor,
                "max_floor": max_floor,
                "limit": limit,
            },
            "count": len(results),
            "items": results,
        }
