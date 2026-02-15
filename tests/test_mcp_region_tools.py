from __future__ import annotations

import json
from collections.abc import Mapping

import pytest
from mcp.server.fastmcp import FastMCP

from src.mcp_server.server import create_mcp_server


@pytest.fixture
def mcp_server() -> FastMCP:
    return create_mcp_server(enabled_tools=["list_regions", "search_regions"])


def _normalize_payload(mapping: Mapping[object, object]) -> dict[str, object]:
    return {str(key): value for key, value in mapping.items()}


def _extract_payload(tool_result: object) -> dict[str, object]:
    if isinstance(tool_result, dict):
        return _normalize_payload(tool_result)

    if isinstance(tool_result, tuple):
        for part in tool_result:
            if isinstance(part, dict):
                return _normalize_payload(part)
            if isinstance(part, list) and part:
                maybe_text = getattr(part[0], "text", None)
                if isinstance(maybe_text, str):
                    loaded = json.loads(maybe_text)
                    if isinstance(loaded, dict):
                        return _normalize_payload(loaded)

    raise AssertionError("Failed to extract MCP payload dict")


def _extract_regions(payload: dict[str, object]) -> list[dict[str, object]]:
    regions_raw = payload.get("regions")
    assert isinstance(regions_raw, list)

    regions: list[dict[str, object]] = []
    for region in regions_raw:
        assert isinstance(region, dict)
        regions.append(_normalize_payload(region))
    return regions


@pytest.mark.anyio
async def test_list_regions_default_count_matches_length(mcp_server: FastMCP) -> None:
    result = await mcp_server.call_tool("list_regions", {})
    payload = _extract_payload(result)
    regions = _extract_regions(payload)

    assert payload["count"] == len(regions)
    assert len(regions) > 0


@pytest.mark.anyio
async def test_list_regions_filters_by_sido(mcp_server: FastMCP) -> None:
    result = await mcp_server.call_tool("list_regions", {"sido": "서울특별시"})
    payload = _extract_payload(result)
    regions = _extract_regions(payload)

    assert payload["count"] == len(regions)
    assert len(regions) > 0
    assert all(region.get("sido") == "서울특별시" for region in regions)


@pytest.mark.anyio
async def test_list_regions_detailed_format_contains_full_name(
    mcp_server: FastMCP,
) -> None:
    result = await mcp_server.call_tool(
        "list_regions",
        {"sido": "서울특별시", "sigungu": "종로구", "format": "detailed"},
    )
    payload = _extract_payload(result)
    regions = _extract_regions(payload)

    assert payload["count"] == len(regions)
    assert len(regions) == 1
    assert regions[0]["full_name"] == "서울특별시 종로구"


@pytest.mark.anyio
async def test_list_regions_sigungu_partial_match_returns_expected_regions(
    mcp_server: FastMCP,
) -> None:
    result = await mcp_server.call_tool(
        "list_regions",
        {"sido": "경기도", "sigungu": "분당구"},
    )
    payload = _extract_payload(result)
    regions = _extract_regions(payload)

    assert payload["count"] == len(regions)
    assert len(regions) > 0
    assert all(region.get("sido") == "경기도" for region in regions)
    assert all("분당구" in str(region.get("sigungu", "")) for region in regions)
    assert any(region.get("sigungu") == "성남시분당구" for region in regions)


@pytest.mark.anyio
async def test_search_regions_applies_limit_and_partial_match(
    mcp_server: FastMCP,
) -> None:
    limit = 3
    result = await mcp_server.call_tool(
        "search_regions", {"query": "구", "limit": limit}
    )
    payload = _extract_payload(result)
    regions = _extract_regions(payload)

    assert payload["count"] == len(regions)
    assert len(regions) <= limit
    assert all(
        "구" in str(region.get("full_name", ""))
        or "구" in str(region.get("sigungu", ""))
        or "구" in str(region.get("sido", ""))
        for region in regions
    )
