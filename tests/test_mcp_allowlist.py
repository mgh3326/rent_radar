from __future__ import annotations

from collections.abc import Iterator

import pytest
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from src.config.settings import get_settings
from src.mcp_server.server import create_mcp_server

ALL_TOOL_NAMES = {
    "add_favorite",
    "check_jeonse_safety",
    "compare_listings",
    "get_price_trend",
    "get_real_price",
    "list_favorites",
    "list_regions",
    "manage_favorites",
    "remove_favorite",
    "search_rent",
    "search_regions",
}


@pytest.fixture(autouse=True)
def clear_settings_cache() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def _list_tool_names(mcp_server: FastMCP) -> set[str]:
    tools = await mcp_server.list_tools()
    return {tool.name for tool in tools}


@pytest.mark.anyio
@pytest.mark.parametrize("allowlist_value", [None, ""])
async def test_allowlist_off_registers_all_tools(
    monkeypatch: pytest.MonkeyPatch,
    allowlist_value: str | None,
) -> None:
    if allowlist_value is None:
        monkeypatch.delenv("MCP_ENABLED_TOOLS", raising=False)
    else:
        monkeypatch.setenv("MCP_ENABLED_TOOLS", allowlist_value)

    mcp_server = create_mcp_server()
    tool_names = await _list_tool_names(mcp_server)

    assert tool_names == ALL_TOOL_NAMES
    assert len(tool_names) == 11


@pytest.mark.anyio
async def test_allowlist_on_keeps_only_allowed_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MCP_ENABLED_TOOLS", "search_rent,list_regions")

    mcp_server = create_mcp_server()
    tool_names = await _list_tool_names(mcp_server)

    assert tool_names == {"search_rent", "list_regions"}


@pytest.mark.anyio
async def test_allowlist_env_value_is_normalized_and_deduplicated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "MCP_ENABLED_TOOLS",
        " Search_Rent , list_regions , SEARCH_RENT ",
    )

    mcp_server = create_mcp_server()
    tool_names = await _list_tool_names(mcp_server)

    assert tool_names == {"search_rent", "list_regions"}


@pytest.mark.anyio
async def test_allowlist_argument_is_normalized_and_deduplicated() -> None:
    mcp_server = create_mcp_server(
        enabled_tools=["search_rent", "LIST_REGIONS", " search_rent "]
    )
    tool_names = await _list_tool_names(mcp_server)

    assert tool_names == {"search_rent", "list_regions"}


@pytest.mark.anyio
async def test_calling_filtered_out_tool_returns_unknown_tool_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MCP_ENABLED_TOOLS", "search_rent,list_regions")
    mcp_server = create_mcp_server()

    with pytest.raises(ToolError, match="Unknown tool"):
        _ = await mcp_server.call_tool(
            "manage_favorites", {"action": "list", "user_id": "u1"}
        )


@pytest.mark.anyio
async def test_invalid_allowlist_value_fails_fast(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MCP_ENABLED_TOOLS", "search_rent,not_a_real_tool")

    with pytest.raises(ValueError) as exc_info:
        _ = create_mcp_server()

    error_message = str(exc_info.value)
    assert "Invalid MCP_ENABLED_TOOLS entries" in error_message
    assert "not_a_real_tool" in error_message
    assert "Valid values are:" in error_message
    assert "search_rent" in error_message
