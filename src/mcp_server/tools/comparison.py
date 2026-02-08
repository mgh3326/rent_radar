"""MCP tools for listing comparison."""

from mcp.server.fastmcp import FastMCP

from src.db.session import session_context
from src.services.comparison_service import ComparisonService


def register_comparison_tools(mcp: FastMCP) -> None:
    """Register comparison-related tools on a FastMCP server."""

    @mcp.tool(name="compare_listings")
    async def compare_listings(
        listing_ids: list[int] | None = None,
    ) -> dict[str, object]:
        """Compare multiple listings side by side.

        Args:
            listing_ids: List of listing IDs to compare (2-10 listings supported)

        Returns:
            Detailed comparison with per-listing data and summary statistics
        """

        if listing_ids is None or not listing_ids:
            return {
                "status": "error",
                "message": "No listing IDs provided",
                "comparisons": [],
            }

        async with session_context() as session:
            service = ComparisonService(session)
            result = await service.compare_listings(listing_ids)

        return result
