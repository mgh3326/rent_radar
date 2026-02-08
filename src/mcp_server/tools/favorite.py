"""MCP tools for favorite management."""

from mcp.server.fastmcp import FastMCP

from src.db.session import session_context
from src.services.favorite_service import FavoriteService


def register_favorite_tools(mcp: FastMCP) -> None:
    """Register favorite-related tools on a FastMCP server."""

    @mcp.tool(name="add_favorite")
    async def add_favorite(user_id: str, listing_id: int) -> dict[str, object]:
        """Add a listing to user favorites.

        Args:
            user_id: User identifier (e.g., email or user ID)
            listing_id: Listing ID to add to favorites

        Returns:
            Status indicating if the listing was added or already existed
        """

        async with session_context() as session:
            service = FavoriteService(session)
            result = await service.add_favorite(user_id, listing_id)

        return result

    @mcp.tool(name="list_favorites")
    async def list_favorites(user_id: str, limit: int = 50) -> dict[str, object]:
        """List all favorites for a user with listing details.

        Args:
            user_id: User identifier
            limit: Maximum number of results to return (default: 50)

        Returns:
            List of favorites with full listing details
        """

        async with session_context() as session:
            service = FavoriteService(session)
            results = await service.list_favorites(user_id, limit)

        return {"user_id": user_id, "count": len(results), "items": results}

    @mcp.tool(name="remove_favorite")
    async def remove_favorite(user_id: str, listing_id: int) -> dict[str, object]:
        """Remove a listing from user favorites.

        Args:
            user_id: User identifier
            listing_id: Listing ID to remove from favorites

        Returns:
            Status indicating if the favorite was removed or not found
        """

        async with session_context() as session:
            service = FavoriteService(session)
            result = await service.remove_favorite(user_id, listing_id)

        return result
