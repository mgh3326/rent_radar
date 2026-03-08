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
