"""MCP tools for jeonse safety checks."""

from decimal import Decimal

from mcp.server.fastmcp import FastMCP

from src.db.repositories import fetch_listings_by_ids
from src.db.session import session_context
from src.services.safety_service import SafetyService


def register_safety_tools(mcp: FastMCP) -> None:
    """Register safety-related tools on a FastMCP server."""

    @mcp.tool(name="check_jeonse_safety")
    async def check_jeonse_safety(
        deposit: int | None = None,
        property_type: str | None = None,
        region_code: str | None = None,
        dong: str | None = None,
        area_m2: float | None = None,
        period_months: int = 12,
        listing_id: int | None = None,
    ) -> dict[str, object]:
        """Check if a jeonse deposit is safe compared to sale prices.

        Args:
            deposit: Jeonse deposit amount in 10,000 won units (e.g., 50000 = 500 million won)
            property_type: Property type - "apt" (아파트), "villa" (연립다세대), "officetel" (오피스텔)
            region_code: 5-digit region code (e.g., 11110 for Jongno-gu)
            dong: Legal dong name (optional, for more precise comparison)
            area_m2: Property area in square meters (optional, for filtering similar properties)
            period_months: How many months of sale data to consider (default: 12)
            listing_id: Listing ID to auto-fill deposit, property_type, dong, area_m2

        Returns:
            Safety analysis including:
            - status: "safe", "caution", or "unsafe"
            - safety_ratio: deposit / avg_sale_price
            - avg_sale_price: Average sale price of comparable properties
            - min_sale_price: Minimum sale price of comparable properties
            - max_sale_price: Maximum sale price of comparable properties
            - comparable_sales_count: Number of comparable sale records found
        """

        async with session_context() as session:
            resolved_deposit = deposit
            resolved_property_type = property_type
            resolved_dong = dong
            resolved_area_m2 = Decimal(str(area_m2)) if area_m2 is not None else None

            if listing_id is not None:
                listings = await fetch_listings_by_ids(session, [listing_id])
                if listings:
                    lst = listings[0]
                    resolved_deposit = (
                        resolved_deposit
                        if resolved_deposit is not None
                        else lst.deposit
                    )
                    resolved_property_type = resolved_property_type or lst.property_type
                    resolved_dong = resolved_dong or lst.dong
                    if resolved_area_m2 is None and lst.area_m2 is not None:
                        resolved_area_m2 = lst.area_m2

            if resolved_deposit is None or resolved_property_type is None:
                return {
                    "status": "error",
                    "message": "deposit and property_type are required (or provide listing_id)",
                    "safety_ratio": None,
                    "avg_sale_price": None,
                }

            service = SafetyService(session)
            result = await service.check_jeonse_safety(
                deposit=resolved_deposit,
                property_type=resolved_property_type,
                region_code=region_code,
                dong=resolved_dong,
                area_m2=resolved_area_m2,
                period_months=period_months,
            )

        return result
