"""MCP server entrypoint using official mcp.server.fastmcp."""

from mcp.server.fastmcp import FastMCP

from src.mcp_server.tools.price import register_price_tools

mcp = FastMCP("rent-finder", json_response=True)
register_price_tools(mcp)


def main() -> None:
    """Run MCP server via stdio transport."""

    mcp.run()


if __name__ == "__main__":
    main()
