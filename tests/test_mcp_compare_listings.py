from __future__ import annotations

import json
from collections.abc import Mapping
from contextlib import asynccontextmanager
from typing import Any

import pytest
from mcp.server.fastmcp import FastMCP

from src.mcp_server.server import create_mcp_server
from src.mcp_server.tools import comparison as comparison_tools


@pytest.fixture
def mcp_server() -> FastMCP:
    return create_mcp_server(enabled_tools=["compare_listings"])


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


@pytest.fixture(autouse=True)
def patch_session_context(monkeypatch: pytest.MonkeyPatch) -> None:
    @asynccontextmanager
    async def fake_session_context():
        yield object()

    monkeypatch.setattr(comparison_tools, "session_context", fake_session_context)


@pytest.mark.anyio
async def test_compare_listings_rejects_missing_listing_ids(
    mcp_server: FastMCP,
) -> None:
    result = await mcp_server.call_tool("compare_listings", {})
    payload = _extract_payload(result)

    assert payload["status"] == "error"
    assert payload["message"] == "No listing IDs provided"
    assert payload["comparisons"] == []


@pytest.mark.anyio
async def test_compare_listings_rejects_empty_listing_ids(mcp_server: FastMCP) -> None:
    result = await mcp_server.call_tool("compare_listings", {"listing_ids": []})
    payload = _extract_payload(result)

    assert payload["status"] == "error"
    assert payload["message"] == "No listing IDs provided"
    assert payload["comparisons"] == []


@pytest.mark.anyio
async def test_compare_listings_rejects_one_listing(mcp_server: FastMCP) -> None:
    result = await mcp_server.call_tool("compare_listings", {"listing_ids": [1001]})
    payload = _extract_payload(result)

    assert payload["status"] == "error"
    assert payload["message"] == "At least 2 listings required for comparison"
    assert payload["comparisons"] == []


@pytest.mark.anyio
async def test_compare_listings_rejects_eleven_listings(mcp_server: FastMCP) -> None:
    result = await mcp_server.call_tool(
        "compare_listings",
        {"listing_ids": list(range(1, 12))},
    )
    payload = _extract_payload(result)

    assert payload["status"] == "error"
    assert payload["message"] == "Maximum 10 listings can be compared"
    assert payload["comparisons"] == []


@pytest.mark.anyio
async def test_compare_listings_success_passthrough_contract(
    monkeypatch: pytest.MonkeyPatch,
    mcp_server: FastMCP,
) -> None:
    async def fake_compare_listings(
        self: Any,
        listing_ids: list[int],
    ) -> dict[str, object]:
        assert listing_ids == [101, 102]
        return {
            "status": "success",
            "listing_count": 2,
            "comparisons": [
                {
                    "id": 101,
                    "deposit": 58000,
                    "market_avg_deposit": None,
                    "market_sample_count": 0,
                },
                {
                    "id": 102,
                    "deposit": 22000,
                    "market_avg_deposit": None,
                    "market_sample_count": 0,
                },
            ],
            "summary": {
                "min_deposit": 22000,
                "max_deposit": 58000,
                "avg_deposit": 40000,
            },
        }

    monkeypatch.setattr(
        comparison_tools.ComparisonService,
        "compare_listings",
        fake_compare_listings,
    )

    result = await mcp_server.call_tool("compare_listings", {"listing_ids": [101, 102]})
    payload = _extract_payload(result)

    comparisons_raw = payload.get("comparisons")
    assert payload["status"] == "success"
    assert payload["listing_count"] == 2
    assert isinstance(comparisons_raw, list)
    assert len(comparisons_raw) == 2
    assert isinstance(payload.get("summary"), dict)
