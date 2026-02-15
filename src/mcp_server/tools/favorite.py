"""MCP tools for favorite management."""

from mcp.server.fastmcp import FastMCP

from src.db.session import session_context
from src.services.favorite_service import FavoriteService


def register_favorite_tools(mcp: FastMCP) -> None:
    """Register favorite-related tools on a FastMCP server."""

    @mcp.tool(name="add_favorite")
    async def add_favorite(user_id: str, listing_id: int) -> dict[str, object]:
        async with session_context() as session:
            service = FavoriteService(session)
            result = await service.add_favorite(user_id, listing_id)
        return result

    @mcp.tool(name="list_favorites")
    async def list_favorites(user_id: str, limit: int = 50) -> dict[str, object]:
        async with session_context() as session:
            service = FavoriteService(session)
            results = await service.list_favorites(user_id, limit)
        return {"user_id": user_id, "count": len(results), "items": results}

    @mcp.tool(name="remove_favorite")
    async def remove_favorite(user_id: str, listing_id: int) -> dict[str, object]:
        async with session_context() as session:
            service = FavoriteService(session)
            result = await service.remove_favorite(user_id, listing_id)
        return result

    @mcp.tool(name="manage_favorites")
    async def manage_favorites(
        action: str,
        user_id: str,
        listing_id: int | None = None,
        limit: int = 50,
    ) -> dict[str, object]:
        async with session_context() as session:
            service = FavoriteService(session)

            if action == "add":
                if listing_id is None:
                    return {
                        "error": "listing_id required for add action",
                        "success": False,
                    }
                result = await service.add_favorite(user_id, listing_id)
                result["action"] = "add"
                return result

            elif action == "remove":
                if listing_id is None:
                    return {
                        "error": "listing_id required for remove action",
                        "success": False,
                    }
                result = await service.remove_favorite(user_id, listing_id)
                result["action"] = "remove"
                return result

            elif action == "list":
                results = await service.list_favorites(user_id, limit)
                return {
                    "action": "list",
                    "user_id": user_id,
                    "count": len(results),
                    "items": results,
                    "success": True,
                }

            else:
                return {
                    "error": f"Unknown action: {action}. Use 'add', 'remove', or 'list'.",
                    "success": False,
                }
