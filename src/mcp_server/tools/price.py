"""MCP tools for real-trade prices and trends."""

from mcp.server.fastmcp import FastMCP

from src.db.session import session_context
from src.services.price_service import PriceService


def register_price_tools(mcp: FastMCP) -> None:
    """Register price-related tools on a FastMCP server."""

    @mcp.tool(name="get_real_price")
    async def get_real_price(
        region: str,
        dong: str | None = None,
        property_type: str = "apt",
        period_months: int = 6,
    ) -> dict[str, object]:
        """Return rent real-trade history for a region/dong."""

        if period_months <= 0:
            raise ValueError("period_months must be greater than 0")

        async with session_context() as session:
            service = PriceService(session)
            rows = await service.get_real_price(
                region=region,
                dong=dong,
                property_type=property_type,
                period_months=period_months,
            )
        return {
            "query": {
                "region": region,
                "dong": dong,
                "property_type": property_type,
                "period_months": period_months,
            },
            "count": len(rows),
            "items": rows,
        }

    @mcp.tool(name="get_price_trend")
    async def get_price_trend(
        region: str,
        dong: str | None = None,
        property_type: str = "apt",
        period_months: int = 12,
    ) -> dict[str, object]:
        """Return monthly average rent trend for a region/dong."""

        if period_months <= 0:
            raise ValueError("period_months must be greater than 0")

        async with session_context() as session:
            service = PriceService(session)
            trend = await service.get_price_trend(
                region=region,
                dong=dong,
                property_type=property_type,
                period_months=period_months,
            )
        return {
            "query": {
                "region": region,
                "dong": dong,
                "property_type": property_type,
                "period_months": period_months,
            },
            "count": len(trend),
            "trend": trend,
        }
