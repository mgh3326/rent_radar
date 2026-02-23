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


def _extract_crawl_status(payload: dict[str, object]) -> dict[str, object]:
    raw_status = payload.get("crawl_status")
    assert isinstance(raw_status, dict)
    return _normalize_payload(raw_status)


@pytest.fixture(autouse=True)
def _patch_default_crawl_status(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_evaluate_crawl_status(
        self: Any,  # noqa: ARG001
        *,
        region_code: str | None,
        stale_hours: int = 48,
        source: str = "zigbang",
    ) -> dict[str, object]:
        normalized_region = region_code.strip() if region_code else None
        if not normalized_region:
            return {
                "source": source,
                "region_code": None,
                "evaluated": False,
                "needs_crawl": None,
                "reason": "no_region_filter",
                "last_seen_at": None,
                "stale_threshold_hours": stale_hours,
            }

        return {
            "source": source,
            "region_code": normalized_region,
            "evaluated": True,
            "needs_crawl": False,
            "reason": "fresh_data",
            "last_seen_at": None,
            "stale_threshold_hours": stale_hours,
        }

    monkeypatch.setattr(
        listing_tools.ListingService,
        "evaluate_crawl_status",
        fake_evaluate_crawl_status,
        raising=False,
    )


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
    items = _extract_items(payload)

    assert payload["cache_hit"] is False
    assert payload["count"] == len(sample_items)
    assert payload["items"] == sample_items
    assert payload["count"] == len(items)
    assert search_kwargs["dong"] == "MCP_TEST"
    assert search_kwargs["limit"] == 2
    assert len(cache_set_calls) == 1


@pytest.mark.anyio
async def test_search_rent_cache_hit_reuses_items_but_skips_listing_search(
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

    session_context_calls = 0

    @asynccontextmanager
    async def fake_session_context():
        nonlocal session_context_calls
        session_context_calls += 1
        yield object()

    async def forbidden_search_listings(
        self: Any,
        **kwargs: Any,  # noqa: ARG001
    ) -> list[dict[str, object]]:
        raise AssertionError("search_listings must not be called on cache hit")

    monkeypatch.setattr(listing_tools, "cache_get", fake_cache_get)
    monkeypatch.setattr(listing_tools, "cache_set", fake_cache_set)
    monkeypatch.setattr(listing_tools, "session_context", fake_session_context)
    monkeypatch.setattr(
        listing_tools.ListingService,
        "search_listings",
        forbidden_search_listings,
    )

    result = await mcp.call_tool("search_rent", {"dong": "MCP_TEST", "limit": 1})
    payload = _extract_payload(result)
    items = _extract_items(payload)

    assert payload["count"] == 1
    assert payload["cache_hit"] is True
    assert payload["count"] == len(items)
    assert _extract_query(payload)["limit"] == 1
    assert items[0]["source_id"] == "cached-7"
    assert session_context_calls == 1


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
    assert payload["message"] == listing_tools.EMPTY_RESULTS_MESSAGE


@pytest.mark.anyio
async def test_search_rent_cache_hit_empty_result_adds_data_source_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cached_payload = {
        "query": {"dong": "MCP_TEST", "limit": 3},
        "count": 0,
        "items": [],
        "cache_hit": False,
    }

    async def fake_cache_get(_key: str) -> str:
        return json.dumps(cached_payload, ensure_ascii=False)

    async def fake_cache_set(_key: str, _value: Any, _ttl_seconds: int) -> None:
        return None

    @asynccontextmanager
    async def fake_session_context():
        yield object()

    async def forbidden_search_listings(
        self: Any,
        **kwargs: Any,  # noqa: ARG001
    ) -> list[dict[str, object]]:
        raise AssertionError("search_listings must not be called on cache hit")

    monkeypatch.setattr(listing_tools, "cache_get", fake_cache_get)
    monkeypatch.setattr(listing_tools, "cache_set", fake_cache_set)
    monkeypatch.setattr(listing_tools, "session_context", fake_session_context)
    monkeypatch.setattr(
        listing_tools.ListingService,
        "search_listings",
        forbidden_search_listings,
    )

    result = await mcp.call_tool("search_rent", {"dong": "MCP_TEST", "limit": 3})
    payload = _extract_payload(result)

    assert payload["count"] == 0
    assert payload["items"] == []
    assert payload["cache_hit"] is True
    assert payload["message"] == listing_tools.EMPTY_RESULTS_MESSAGE


@pytest.mark.anyio
async def test_search_rent_count_matches_items_length_on_cache_miss(
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
        return [
            {
                "id": 1,
                "source": "zigbang_test_seed",
                "source_id": "m1",
                "dong": "MCP_TEST",
            },
            {
                "id": 2,
                "source": "zigbang_test_seed",
                "source_id": "m2",
                "dong": "MCP_TEST",
            },
        ]

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
    items = _extract_items(payload)

    assert payload["cache_hit"] is False
    assert payload["count"] == len(items)


@pytest.mark.anyio
async def test_search_rent_limit_one_returns_at_most_one_item(
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
        limit = int(kwargs.get("limit", 50))
        seed: list[dict[str, object]] = [
            {
                "id": 11,
                "source": "zigbang_test_seed",
                "source_id": "l1",
                "dong": "MCP_TEST",
            },
            {
                "id": 12,
                "source": "zigbang_test_seed",
                "source_id": "l2",
                "dong": "MCP_TEST",
            },
            {
                "id": 13,
                "source": "zigbang_test_seed",
                "source_id": "l3",
                "dong": "MCP_TEST",
            },
        ]
        return seed[:limit]

    monkeypatch.setattr(listing_tools, "cache_get", fake_cache_get)
    monkeypatch.setattr(listing_tools, "cache_set", fake_cache_set)
    monkeypatch.setattr(listing_tools, "session_context", fake_session_context)
    monkeypatch.setattr(
        listing_tools.ListingService,
        "search_listings",
        fake_search_listings,
    )

    result = await mcp.call_tool("search_rent", {"dong": "MCP_TEST", "limit": 1})
    payload = _extract_payload(result)
    items = _extract_items(payload)

    assert _extract_query(payload)["limit"] == 1
    assert len(items) <= 1
    assert payload["count"] == len(items)


@pytest.mark.anyio
async def test_search_rent_no_region_filter_includes_crawl_status(
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
    crawl_status = _extract_crawl_status(payload)

    assert crawl_status == {
        "source": "zigbang",
        "region_code": None,
        "evaluated": False,
        "needs_crawl": None,
        "reason": "no_region_filter",
        "last_seen_at": None,
        "stale_threshold_hours": 48,
    }
    assert "crawl_message" not in payload


@pytest.mark.anyio
async def test_search_rent_invalid_region_code_includes_reason(
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

    async def fake_evaluate_crawl_status(
        self: Any,  # noqa: ARG001
        *,
        region_code: str | None,
        stale_hours: int = 48,
        source: str = "zigbang",
    ) -> dict[str, object]:
        assert region_code == "99999"
        return {
            "source": source,
            "region_code": "99999",
            "evaluated": False,
            "needs_crawl": None,
            "reason": "invalid_region_code",
            "last_seen_at": None,
            "stale_threshold_hours": stale_hours,
        }

    monkeypatch.setattr(listing_tools, "cache_get", fake_cache_get)
    monkeypatch.setattr(listing_tools, "cache_set", fake_cache_set)
    monkeypatch.setattr(listing_tools, "session_context", fake_session_context)
    monkeypatch.setattr(
        listing_tools.ListingService,
        "search_listings",
        fake_search_listings,
    )
    monkeypatch.setattr(
        listing_tools.ListingService,
        "evaluate_crawl_status",
        fake_evaluate_crawl_status,
        raising=False,
    )

    result = await mcp.call_tool("search_rent", {"region_code": "99999", "limit": 3})
    payload = _extract_payload(result)
    crawl_status = _extract_crawl_status(payload)

    assert crawl_status["reason"] == "invalid_region_code"
    assert crawl_status["evaluated"] is False
    assert crawl_status["needs_crawl"] is None
    assert "crawl_message" not in payload


@pytest.mark.anyio
async def test_search_rent_needs_crawl_when_no_region_data(
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

    async def fake_evaluate_crawl_status(
        self: Any,  # noqa: ARG001
        *,
        region_code: str | None,
        stale_hours: int = 48,
        source: str = "zigbang",
    ) -> dict[str, object]:
        return {
            "source": source,
            "region_code": region_code,
            "evaluated": True,
            "needs_crawl": True,
            "reason": "no_region_data",
            "last_seen_at": None,
            "stale_threshold_hours": stale_hours,
        }

    monkeypatch.setattr(listing_tools, "cache_get", fake_cache_get)
    monkeypatch.setattr(listing_tools, "cache_set", fake_cache_set)
    monkeypatch.setattr(listing_tools, "session_context", fake_session_context)
    monkeypatch.setattr(
        listing_tools.ListingService,
        "search_listings",
        fake_search_listings,
    )
    monkeypatch.setattr(
        listing_tools.ListingService,
        "evaluate_crawl_status",
        fake_evaluate_crawl_status,
        raising=False,
    )

    result = await mcp.call_tool("search_rent", {"region_code": "11110", "limit": 3})
    payload = _extract_payload(result)
    crawl_status = _extract_crawl_status(payload)

    assert crawl_status["needs_crawl"] is True
    assert crawl_status["reason"] == "no_region_data"
    assert isinstance(payload.get("crawl_message"), str)
    assert payload.get("crawl_message")


@pytest.mark.anyio
async def test_search_rent_needs_crawl_when_stale(
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

    async def fake_evaluate_crawl_status(
        self: Any,  # noqa: ARG001
        *,
        region_code: str | None,
        stale_hours: int = 48,
        source: str = "zigbang",
    ) -> dict[str, object]:
        return {
            "source": source,
            "region_code": region_code,
            "evaluated": True,
            "needs_crawl": True,
            "reason": "stale_data",
            "last_seen_at": "2026-02-18T00:00:00+00:00",
            "stale_threshold_hours": stale_hours,
        }

    monkeypatch.setattr(listing_tools, "cache_get", fake_cache_get)
    monkeypatch.setattr(listing_tools, "cache_set", fake_cache_set)
    monkeypatch.setattr(listing_tools, "session_context", fake_session_context)
    monkeypatch.setattr(
        listing_tools.ListingService,
        "search_listings",
        fake_search_listings,
    )
    monkeypatch.setattr(
        listing_tools.ListingService,
        "evaluate_crawl_status",
        fake_evaluate_crawl_status,
        raising=False,
    )

    result = await mcp.call_tool("search_rent", {"region_code": "11110", "limit": 3})
    payload = _extract_payload(result)
    crawl_status = _extract_crawl_status(payload)

    assert crawl_status["needs_crawl"] is True
    assert crawl_status["reason"] == "stale_data"
    assert isinstance(payload.get("crawl_message"), str)
    assert payload.get("crawl_message")


@pytest.mark.anyio
async def test_search_rent_fresh_data_has_no_crawl_message(
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

    async def fake_evaluate_crawl_status(
        self: Any,  # noqa: ARG001
        *,
        region_code: str | None,
        stale_hours: int = 48,
        source: str = "zigbang",
    ) -> dict[str, object]:
        return {
            "source": source,
            "region_code": region_code,
            "evaluated": True,
            "needs_crawl": False,
            "reason": "fresh_data",
            "last_seen_at": "2026-02-20T00:00:00+00:00",
            "stale_threshold_hours": stale_hours,
        }

    monkeypatch.setattr(listing_tools, "cache_get", fake_cache_get)
    monkeypatch.setattr(listing_tools, "cache_set", fake_cache_set)
    monkeypatch.setattr(listing_tools, "session_context", fake_session_context)
    monkeypatch.setattr(
        listing_tools.ListingService,
        "search_listings",
        fake_search_listings,
    )
    monkeypatch.setattr(
        listing_tools.ListingService,
        "evaluate_crawl_status",
        fake_evaluate_crawl_status,
        raising=False,
    )

    result = await mcp.call_tool("search_rent", {"region_code": "11110", "limit": 3})
    payload = _extract_payload(result)
    crawl_status = _extract_crawl_status(payload)

    assert crawl_status["needs_crawl"] is False
    assert crawl_status["reason"] == "fresh_data"
    assert "crawl_message" not in payload


@pytest.mark.anyio
async def test_search_rent_cache_hit_re_evaluates_crawl_status_each_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cached_payload = {
        "query": {"region_code": "11110", "limit": 1},
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
        "crawl_status": {
            "source": "zigbang",
            "region_code": "11110",
            "evaluated": True,
            "needs_crawl": False,
            "reason": "fresh_data",
            "last_seen_at": "2026-02-20T09:00:00+00:00",
            "stale_threshold_hours": 48,
        },
    }

    async def fake_cache_get(_key: str) -> str:
        return json.dumps(cached_payload, ensure_ascii=False)

    async def fake_cache_set(_key: str, _value: Any, _ttl_seconds: int) -> None:
        return None

    @asynccontextmanager
    async def fake_session_context():
        yield object()

    async def forbidden_search_listings(
        self: Any,
        **kwargs: Any,  # noqa: ARG001
    ) -> list[dict[str, object]]:
        raise AssertionError("search_listings must not be called on cache hit")

    call_count = 0

    async def fake_evaluate_crawl_status(
        self: Any,  # noqa: ARG001
        *,
        region_code: str | None,
        stale_hours: int = 48,
        source: str = "zigbang",
    ) -> dict[str, object]:
        nonlocal call_count
        call_count += 1
        assert region_code == "11110"
        return {
            "source": source,
            "region_code": region_code,
            "evaluated": True,
            "needs_crawl": True,
            "reason": "stale_data",
            "last_seen_at": "2026-02-17T09:00:00+00:00",
            "stale_threshold_hours": stale_hours,
        }

    monkeypatch.setattr(listing_tools, "cache_get", fake_cache_get)
    monkeypatch.setattr(listing_tools, "cache_set", fake_cache_set)
    monkeypatch.setattr(listing_tools, "session_context", fake_session_context)
    monkeypatch.setattr(
        listing_tools.ListingService,
        "search_listings",
        forbidden_search_listings,
    )
    monkeypatch.setattr(
        listing_tools.ListingService,
        "evaluate_crawl_status",
        fake_evaluate_crawl_status,
        raising=False,
    )

    result = await mcp.call_tool("search_rent", {"region_code": "11110", "limit": 1})
    payload = _extract_payload(result)
    crawl_status = _extract_crawl_status(payload)

    assert payload["cache_hit"] is True
    assert call_count == 1
    assert crawl_status["needs_crawl"] is True
    assert crawl_status["reason"] == "stale_data"
    assert isinstance(payload.get("crawl_message"), str)
    assert payload.get("crawl_message")
