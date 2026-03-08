from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast

import pytest

from src.db.repositories import BaselineComparisonStats
from src.mcp_server.server import create_mcp_server
from src.mcp_server.tools import recommendation as recommendation_tools
from src.services.place_query_recommendation_service import (
    PlaceQueryRecommendationService,
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


def _make_listing(**overrides: Any) -> SimpleNamespace:
    now = datetime(2026, 3, 7, 12, 0, tzinfo=UTC)
    payload: dict[str, Any] = {
        "id": 1,
        "source": "zigbang_test_seed",
        "source_id": "seed-1",
        "property_type": "villa",
        "rent_type": "monthly",
        "deposit": 10000,
        "monthly_rent": 50,
        "address": "서울 종로구 사직동",
        "dong": "사직동",
        "detail_address": None,
        "area_m2": Decimal("40.0"),
        "floor": 5,
        "total_floors": 10,
        "description": "sample",
        "latitude": Decimal("37.572"),
        "longitude": Decimal("126.976"),
        "is_active": True,
        "first_seen_at": now - timedelta(days=5),
        "last_seen_at": now - timedelta(days=1),
        "created_at": now - timedelta(days=5),
        "updated_at": now,
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


@pytest.mark.anyio
async def test_recommend_listings_tool_is_registered() -> None:
    mcp_server = create_mcp_server()
    tool_names = {tool.name for tool in await mcp_server.list_tools()}

    assert "recommend_listings" in tool_names


@pytest.mark.anyio
async def test_recommend_by_place_query_tool_is_registered() -> None:
    mcp_server = create_mcp_server()
    tool_names = {tool.name for tool in await mcp_server.list_tools()}

    assert "recommend_by_place_query" in tool_names


@pytest.mark.anyio
async def test_recommend_listings_contract_defaults_fields_and_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    villa_listing = _make_listing(id=1, source_id="seed-villa", property_type="villa")
    officetel_listing = _make_listing(
        id=2,
        source_id="seed-officetel",
        property_type="officetel",
        last_seen_at=datetime(2026, 3, 7, 13, 0, tzinfo=UTC),
    )

    @asynccontextmanager
    async def fake_session_context() -> AsyncIterator[object]:
        yield object()

    async def fake_evaluate(
        self: Any,
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
            "last_seen_at": None,
            "stale_threshold_hours": stale_hours,
        }

    async def fake_fetch_listings(_session: object, **kwargs: Any) -> list[object]:
        property_type = kwargs["property_type"]
        if property_type == "villa":
            return [villa_listing]
        if property_type == "officetel":
            return [officetel_listing]
        return []

    async def fake_fetch_baseline(
        _session: object,
        **kwargs: Any,
    ) -> BaselineComparisonStats:
        return BaselineComparisonStats(
            avg_monthly_cost_per_m2=1000.0,
            sample_count=4,
            scope="region",
        )

    monkeypatch.setattr(recommendation_tools, "session_context", fake_session_context)
    monkeypatch.setattr(
        recommendation_tools.RecommendationService,
        "evaluate_crawl_status",
        fake_evaluate,
        raising=False,
    )
    monkeypatch.setattr(
        "src.services.recommendation_service.fetch_listings",
        fake_fetch_listings,
    )
    monkeypatch.setattr(
        "src.services.recommendation_service.fetch_baseline_comparison_stats",
        fake_fetch_baseline,
    )

    mcp_server = create_mcp_server(enabled_tools=["recommend_listings"])
    tool_names = {tool.name for tool in await mcp_server.list_tools()}
    assert tool_names == {"recommend_listings"}

    result = await mcp_server.call_tool(
        "recommend_listings", {"region_code": "11110", "limit": 5}
    )
    payload = _extract_payload(result)
    items = cast(list[dict[str, object]], payload["items"])
    query = cast(dict[str, object], payload["query"])

    assert query["property_types"] == ["villa", "officetel"]
    assert payload["count"] == len(items)
    assert len(items) == 2
    assert items[0]["rank"] == 1
    assert {
        "rank",
        "recommendation_score",
        "deal_delta_pct",
        "total_monthly_cost",
    } <= set(items[0])


@pytest.mark.anyio
async def test_recommend_by_place_query_contract_defaults_fields_and_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_kwargs: dict[str, object] = {}

    @asynccontextmanager
    async def fake_session_context() -> AsyncIterator[object]:
        yield object()

    async def fake_recommend_by_place_query(
        self: Any,
        **kwargs: Any,
    ) -> dict[str, object]:
        captured_kwargs.update(kwargs)
        return {
            "status": "clarification_needed",
            "query": {
                "place_query": kwargs["place_query"],
                "resolved_dongs": kwargs.get("resolved_dongs"),
                "limit": kwargs["limit"],
            },
            "count": 0,
            "items": [],
            "question": "무슨 동이 맞습니까?",
            "clarification_groups": [
                {
                    "station_name": "평촌역",
                    "options": [
                        {
                            "station_name": "평촌역",
                            "region_code": "41190",
                            "dong": "호계동",
                            "label": "경기도 안양시 동안구 호계동",
                        }
                    ],
                }
            ],
            "parsed_places": ["평촌역"],
            "resolved_dongs": kwargs.get("resolved_dongs") or [],
        }

    monkeypatch.setattr(recommendation_tools, "session_context", fake_session_context)
    monkeypatch.setattr(
        PlaceQueryRecommendationService,
        "recommend_by_place_query",
        fake_recommend_by_place_query,
        raising=False,
    )

    mcp_server = create_mcp_server(enabled_tools=["recommend_by_place_query"])
    tool_names = {tool.name for tool in await mcp_server.list_tools()}
    assert tool_names == {"recommend_by_place_query"}

    result = await mcp_server.call_tool(
        "recommend_by_place_query",
        {
            "place_query": "평촌역 주변에서 추천해줘",
            "resolved_dongs": [
                {
                    "station_name": "평촌역",
                    "region_code": "41190",
                    "dong": "호계동",
                }
            ],
            "limit": 5,
        },
    )
    payload = _extract_payload(result)

    assert captured_kwargs["place_query"] == "평촌역 주변에서 추천해줘"
    assert captured_kwargs["limit"] == 5
    assert captured_kwargs["resolved_dongs"] == [
        {
            "station_name": "평촌역",
            "region_code": "41190",
            "dong": "호계동",
        }
    ]
    assert payload["status"] == "clarification_needed"
    assert payload["question"] == "무슨 동이 맞습니까?"
    assert payload["parsed_places"] == ["평촌역"]
