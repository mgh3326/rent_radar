"""MCP tools for real-trade prices and trends."""

from mcp.server.fastmcp import FastMCP

from src.db.session import session_context
from src.services.price_service import PriceService


def register_price_tools(mcp: FastMCP) -> None:
    """Register price-related tools on a FastMCP server."""

    @mcp.tool(name="get_real_price")
    async def get_real_price(
        region_code: str,
        dong: str | None = None,
        property_type: str = "apt",
        period_months: int = 6,
    ) -> dict[str, object]:
        """Return rent real-trade history for a region/dong.

        Args:
            region_code: 5-digit region code (e.g., 11110 for Jongno-gu)
            dong: Legal dong name (optional, filters by dong name)
            property_type: Property type - "apt" (아파트), "villa" (연립다세대), "officetel" (오피스텔)
            period_months: Number of months to look back (default: 6)
        """

        if period_months <= 0:
            raise ValueError("period_months must be greater than 0")

        async with session_context() as session:
            service = PriceService(session)
            rows = await service.get_real_price(
                region_code=region_code,
                dong=dong,
                property_type=property_type,
                period_months=period_months,
            )
        return {
            "query": {
                "region_code": region_code,
                "dong": dong,
                "property_type": property_type,
                "period_months": period_months,
            },
            "count": len(rows),
            "items": rows,
        }

    @mcp.tool(name="get_price_trend")
    async def get_price_trend(
        region_code: str,
        dong: str | None = None,
        property_type: str = "apt",
        period_months: int = 12,
    ) -> dict[str, object]:
        """Return monthly average rent trend for a region/dong.

        Args:
            region_code: 5-digit region code (e.g., 11110 for Jongno-gu)
            dong: Legal dong name (optional, filters by dong name)
            property_type: Property type - "apt" (아파트), "villa" (연립다세대), "officetel" (오피스텔)
            period_months: Number of months to look back (default: 12)
        """

        if period_months <= 0:
            raise ValueError("period_months must be greater than 0")

        async with session_context() as session:
            service = PriceService(session)
            trend = await service.get_price_trend(
                region_code=region_code,
                dong=dong,
                property_type=property_type,
                period_months=period_months,
            )
        return {
            "query": {
                "region_code": region_code,
                "dong": dong,
                "property_type": property_type,
                "period_months": period_months,
            },
            "count": len(trend),
            "trend": trend,
        }
