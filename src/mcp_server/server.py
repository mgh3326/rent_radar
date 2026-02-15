"""MCP server entrypoint using official mcp.server.fastmcp."""

from collections.abc import Callable

from mcp.server.fastmcp import FastMCP

from src.config import get_settings
from src.mcp_server.tools.price import register_price_tools
from src.mcp_server.tools.listing import register_listing_tools
from src.mcp_server.tools.safety import register_safety_tools
from src.mcp_server.tools.favorite import register_favorite_tools
from src.mcp_server.tools.comparison import register_comparison_tools
from src.mcp_server.tools.region import register_region_tools

ToolRegistrar = Callable[[FastMCP], None]
ToolRegistration = tuple[ToolRegistrar, tuple[str, ...]]

TOOL_REGISTRATIONS: tuple[ToolRegistration, ...] = (
    (register_price_tools, ("get_real_price", "get_price_trend")),
    (register_listing_tools, ("search_rent",)),
    (register_safety_tools, ("check_jeonse_safety",)),
    (
        register_favorite_tools,
        ("add_favorite", "list_favorites", "remove_favorite", "manage_favorites"),
    ),
    (register_comparison_tools, ("compare_listings",)),
    (register_region_tools, ("list_regions", "search_regions")),
)

VALID_MCP_TOOL_NAMES = frozenset(
    tool_name for _, tool_names in TOOL_REGISTRATIONS for tool_name in tool_names
)


def _normalize_tool_names(tool_names: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()

    for raw_name in tool_names:
        tool_name = str(raw_name).strip().lower()
        if not tool_name or tool_name in seen:
            continue
        seen.add(tool_name)
        normalized.append(tool_name)

    return normalized


def create_mcp_server(enabled_tools: list[str] | None = None) -> FastMCP:
    server = FastMCP("rent-finder", json_response=True)

    for register_tools, _ in TOOL_REGISTRATIONS:
        register_tools(server)

    configured_tools = (
        get_settings().mcp_enabled_tools if enabled_tools is None else enabled_tools
    )
    allowlist = _normalize_tool_names(configured_tools)
    if not allowlist:
        return server

    allowlist_set = set(allowlist)
    invalid_tools = sorted(allowlist_set - VALID_MCP_TOOL_NAMES)
    if invalid_tools:
        valid_tools = ", ".join(sorted(VALID_MCP_TOOL_NAMES))
        invalid_value = ", ".join(invalid_tools)
        raise ValueError(
            f"Invalid MCP_ENABLED_TOOLS entries: {invalid_value}. Valid values are: {valid_tools}"
        )

    disallowed_tools = sorted(VALID_MCP_TOOL_NAMES - allowlist_set)
    for tool_name in disallowed_tools:
        server.remove_tool(tool_name)

    return server


mcp = create_mcp_server()


def main() -> None:
    """Run MCP server via stdio transport."""

    mcp.run()


if __name__ == "__main__":
    main()
