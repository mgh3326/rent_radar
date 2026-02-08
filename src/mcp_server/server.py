"""MCP server entrypoint using official mcp.server.fastmcp."""

from mcp.server.fastmcp import FastMCP

from src.mcp_server.tools.price import register_price_tools
from src.mcp_server.tools.listing import register_listing_tools
from src.mcp_server.tools.safety import register_safety_tools
from src.mcp_server.tools.favorite import register_favorite_tools
from src.mcp_server.tools.comparison import register_comparison_tools
from src.mcp_server.tools.region import register_region_tools

mcp = FastMCP("rent-finder", json_response=True)
register_price_tools(mcp)
register_listing_tools(mcp)
register_safety_tools(mcp)
register_favorite_tools(mcp)
register_comparison_tools(mcp)
register_region_tools(mcp)


def main() -> None:
    """Run MCP server via stdio transport."""

    mcp.run()


if __name__ == "__main__":
    main()
