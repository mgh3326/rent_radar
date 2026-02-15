from __future__ import annotations

import json
from collections.abc import Mapping
from contextlib import asynccontextmanager
from typing import Any

import pytest
from mcp.server.fastmcp import FastMCP

from src.mcp_server.server import create_mcp_server
from src.mcp_server.tools import favorite as favorite_tools


@pytest.fixture
def mcp_server() -> FastMCP:
    return create_mcp_server(
        enabled_tools=[
            "add_favorite",
            "list_favorites",
            "remove_favorite",
            "manage_favorites",
        ]
    )


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

    monkeypatch.setattr(favorite_tools, "session_context", fake_session_context)


@pytest.mark.anyio
async def test_add_favorite_success_contract(
    monkeypatch: pytest.MonkeyPatch,
    mcp_server: FastMCP,
) -> None:
    async def fake_add_favorite(
        self: Any, user_id: str, listing_id: int
    ) -> dict[str, object]:  # noqa: ARG001
        return {
            "user_id": user_id,
            "listing_id": listing_id,
            "status": "added",
            "message": "Listing added to favorites",
        }

    monkeypatch.setattr(
        favorite_tools.FavoriteService,
        "add_favorite",
        fake_add_favorite,
    )

    result = await mcp_server.call_tool(
        "add_favorite", {"user_id": "u1", "listing_id": 101}
    )
    payload = _extract_payload(result)

    assert payload["status"] == "added"
    assert payload["user_id"] == "u1"
    assert payload["listing_id"] == 101


@pytest.mark.anyio
async def test_add_favorite_listing_not_found_contract(
    monkeypatch: pytest.MonkeyPatch,
    mcp_server: FastMCP,
) -> None:
    async def fake_add_favorite(
        self: Any, user_id: str, listing_id: int
    ) -> dict[str, object]:  # noqa: ARG001
        return {
            "user_id": user_id,
            "listing_id": listing_id,
            "status": "not_found",
            "message": "Listing not found or inactive",
        }

    monkeypatch.setattr(
        favorite_tools.FavoriteService,
        "add_favorite",
        fake_add_favorite,
    )

    result = await mcp_server.call_tool(
        "add_favorite",
        {"user_id": "u1", "listing_id": 9999999},
    )
    payload = _extract_payload(result)

    assert payload["status"] == "not_found"
    assert "not found" in str(payload["message"]).lower()


@pytest.mark.anyio
async def test_list_favorites_schema_and_count_contract(
    monkeypatch: pytest.MonkeyPatch,
    mcp_server: FastMCP,
) -> None:
    expected_items: list[dict[str, object]] = [
        {
            "favorite_id": 7,
            "user_id": "u1",
            "listing_id": 101,
            "created_at": "2026-02-15T00:00:00+00:00",
            "listing": {
                "id": 101,
                "source": "zigbang_test_seed",
                "source_id": "seed-101",
                "property_type": "apt",
                "rent_type": "jeonse",
                "deposit": 58000,
                "monthly_rent": 0,
                "address": "서울특별시 종로구 MCP_TEST 1",
                "dong": "MCP_TEST",
                "detail_address": "MCP_TEST 101호",
                "area_m2": 84.12,
                "floor": 12,
                "total_floors": 25,
                "description": "seed apt",
                "latitude": 37.57,
                "longitude": 126.97,
            },
        }
    ]

    async def fake_list_favorites(
        self: Any, user_id: str, limit: int
    ) -> list[dict[str, object]]:  # noqa: ARG001
        return expected_items[:limit]

    monkeypatch.setattr(
        favorite_tools.FavoriteService,
        "list_favorites",
        fake_list_favorites,
    )

    result = await mcp_server.call_tool(
        "list_favorites", {"user_id": "u1", "limit": 10}
    )
    payload = _extract_payload(result)

    items_raw = payload.get("items")
    assert isinstance(items_raw, list)
    assert payload["count"] == len(items_raw)
    assert payload["user_id"] == "u1"
    assert len(items_raw) == 1
    assert isinstance(items_raw[0], dict)
    assert "favorite_id" in items_raw[0]
    assert "listing" in items_raw[0]
    assert isinstance(items_raw[0]["listing"], dict)


@pytest.mark.anyio
async def test_remove_favorite_not_found_contract(
    monkeypatch: pytest.MonkeyPatch,
    mcp_server: FastMCP,
) -> None:
    async def fake_remove_favorite(
        self: Any,
        user_id: str,
        listing_id: int,
    ) -> dict[str, object]:
        return {
            "user_id": user_id,
            "listing_id": listing_id,
            "status": "not_found",
            "message": "Favorite not found",
        }

    monkeypatch.setattr(
        favorite_tools.FavoriteService,
        "remove_favorite",
        fake_remove_favorite,
    )

    result = await mcp_server.call_tool(
        "remove_favorite",
        {"user_id": "u1", "listing_id": 9999999},
    )
    payload = _extract_payload(result)

    assert payload["status"] == "not_found"
    assert "not found" in str(payload["message"]).lower()


@pytest.mark.anyio
async def test_manage_favorites_invalid_action_contract(mcp_server: FastMCP) -> None:
    result = await mcp_server.call_tool(
        "manage_favorites",
        {"action": "invalid", "user_id": "u1"},
    )
    payload = _extract_payload(result)

    assert payload["success"] is False
    assert "unknown action" in str(payload["error"]).lower()


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("action", "expected_error"),
    [
        ("add", "listing_id required for add action"),
        ("remove", "listing_id required for remove action"),
    ],
)
async def test_manage_favorites_missing_listing_id_contract(
    action: str,
    expected_error: str,
    mcp_server: FastMCP,
) -> None:
    result = await mcp_server.call_tool(
        "manage_favorites", {"action": action, "user_id": "u1"}
    )
    payload = _extract_payload(result)

    assert payload["success"] is False
    assert payload["error"] == expected_error
