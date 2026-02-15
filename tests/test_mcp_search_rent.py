"""Contract tests for MCP `search_rent` tool."""

from __future__ import annotations

import json
from collections.abc import Mapping
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Any

import pytest

from src.mcp_server.server import mcp
from src.mcp_server.tools import listing as listing_tools


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


def _extract_items(payload: dict[str, object]) -> list[dict[str, object]]:
    raw_items = payload.get("items")
    assert isinstance(raw_items, list)

    items: list[dict[str, object]] = []
    for raw_item in raw_items:
        assert isinstance(raw_item, dict)
        items.append(_normalize_payload(raw_item))
    return items


def _extract_query(payload: dict[str, object]) -> dict[str, object]:
    raw_query = payload.get("query")
    assert isinstance(raw_query, dict)
    return _normalize_payload(raw_query)


@pytest.mark.anyio
async def test_search_rent_cache_miss_uses_service_and_sets_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sample_items: list[dict[str, object]] = [
        {
            "id": 1,
            "source": "zigbang_test_seed",
            "source_id": "seed-1",
            "dong": "MCP_TEST",
        },
        {
            "id": 2,
            "source": "zigbang_test_seed",
            "source_id": "seed-2",
            "dong": "MCP_TEST",
        },
    ]
    search_kwargs: dict[str, Any] = {}
    cache_set_calls: list[tuple[str, Any, int]] = []

    async def fake_cache_get(_key: str) -> None:
        return None

    async def fake_cache_set(key: str, value: Any, ttl_seconds: int) -> None:
        cache_set_calls.append((key, value, ttl_seconds))

    @asynccontextmanager
    async def fake_session_context():
        yield object()

    async def fake_search_listings(self: Any, **kwargs: Any) -> list[dict[str, object]]:  # noqa: ARG001
        search_kwargs.update(kwargs)
        return sample_items

    monkeypatch.setattr(listing_tools, "cache_get", fake_cache_get)
    monkeypatch.setattr(listing_tools, "cache_set", fake_cache_set)
    monkeypatch.setattr(listing_tools, "session_context", fake_session_context)
    monkeypatch.setattr(
        listing_tools.ListingService,
        "search_listings",
        fake_search_listings,
    )

    result = await mcp.call_tool("search_rent", {"dong": "MCP_TEST", "limit": 2})
    payload = _extract_payload(result)

    assert payload["cache_hit"] is False
    assert payload["count"] == len(sample_items)
    assert payload["items"] == sample_items
    assert search_kwargs["dong"] == "MCP_TEST"
    assert search_kwargs["limit"] == 2
    assert len(cache_set_calls) == 1


@pytest.mark.anyio
async def test_search_rent_cache_hit_skips_session_and_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cached_payload = {
        "query": {"dong": "MCP_TEST", "limit": 1},
        "count": 1,
        "items": [
            {
                "id": 7,
                "source": "zigbang_test_seed",
                "source_id": "cached-7",
                "dong": "MCP_TEST",
            }
        ],
        "cache_hit": False,
    }

    async def fake_cache_get(_key: str) -> str:
        return json.dumps(cached_payload, ensure_ascii=False)

    async def fake_cache_set(_key: str, _value: Any, _ttl_seconds: int) -> None:
        return None

    @asynccontextmanager
    async def forbidden_session_context():
        raise AssertionError("session_context must not be called on cache hit")
        yield object()  # pragma: no cover

    async def forbidden_search_listings(
        self: Any,
        **kwargs: Any,  # noqa: ARG001
    ) -> list[dict[str, object]]:
        raise AssertionError("search_listings must not be called on cache hit")

    monkeypatch.setattr(listing_tools, "cache_get", fake_cache_get)
    monkeypatch.setattr(listing_tools, "cache_set", fake_cache_set)
    monkeypatch.setattr(listing_tools, "session_context", forbidden_session_context)
    monkeypatch.setattr(
        listing_tools.ListingService,
        "search_listings",
        forbidden_search_listings,
    )

    result = await mcp.call_tool("search_rent", {"dong": "MCP_TEST", "limit": 1})
    payload = _extract_payload(result)

    assert payload["count"] == 1
    assert payload["cache_hit"] is True
    assert _extract_items(payload)[0]["source_id"] == "cached-7"


@pytest.mark.anyio
async def test_search_rent_converts_min_max_area_to_decimal_and_preserves_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_kwargs: dict[str, Any] = {}

    async def fake_cache_get(_key: str) -> None:
        return None

    async def fake_cache_set(_key: str, _value: Any, _ttl_seconds: int) -> None:
        return None

    @asynccontextmanager
    async def fake_session_context():
        yield object()

    async def fake_search_listings(self: Any, **kwargs: Any) -> list[dict[str, object]]:  # noqa: ARG001
        captured_kwargs.update(kwargs)
        return []

    monkeypatch.setattr(listing_tools, "cache_get", fake_cache_get)
    monkeypatch.setattr(listing_tools, "cache_set", fake_cache_set)
    monkeypatch.setattr(listing_tools, "session_context", fake_session_context)
    monkeypatch.setattr(
        listing_tools.ListingService,
        "search_listings",
        fake_search_listings,
    )

    result = await mcp.call_tool(
        "search_rent",
        {"dong": "MCP_TEST", "min_area": 33.3, "max_area": 75.0, "limit": 7},
    )
    payload = _extract_payload(result)

    assert captured_kwargs["min_area"] == Decimal("33.3")
    assert captured_kwargs["max_area"] == Decimal("75.0")
    assert captured_kwargs["limit"] == 7
    assert _extract_query(payload)["limit"] == 7
    assert payload["cache_hit"] is False


@pytest.mark.anyio
async def test_search_rent_allows_empty_result_without_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_cache_get(_key: str) -> None:
        return None

    async def fake_cache_set(_key: str, _value: Any, _ttl_seconds: int) -> None:
        return None

    @asynccontextmanager
    async def fake_session_context():
        yield object()

    async def fake_search_listings(self: Any, **kwargs: Any) -> list[dict[str, object]]:  # noqa: ARG001
        return []

    monkeypatch.setattr(listing_tools, "cache_get", fake_cache_get)
    monkeypatch.setattr(listing_tools, "cache_set", fake_cache_set)
    monkeypatch.setattr(listing_tools, "session_context", fake_session_context)
    monkeypatch.setattr(
        listing_tools.ListingService,
        "search_listings",
        fake_search_listings,
    )

    result = await mcp.call_tool("search_rent", {"dong": "MCP_TEST", "limit": 3})
    payload = _extract_payload(result)

    assert payload["count"] == 0
    assert payload["items"] == []
    assert payload["cache_hit"] is False
