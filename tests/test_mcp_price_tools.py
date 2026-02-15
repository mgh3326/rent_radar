from __future__ import annotations

import json
from collections.abc import Mapping
from contextlib import asynccontextmanager
from typing import Any

import pytest
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.fastmcp import FastMCP

from src.mcp_server.server import create_mcp_server
from src.mcp_server.tools import price as price_tools


@pytest.fixture
def mcp_server() -> FastMCP:
    return create_mcp_server(enabled_tools=["get_real_price"])


@pytest.fixture(autouse=True)
def patch_session_context(monkeypatch: pytest.MonkeyPatch) -> None:
    @asynccontextmanager
    async def fake_session_context():
        yield object()

    monkeypatch.setattr(price_tools, "session_context", fake_session_context)


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


def _extract_query(payload: dict[str, object]) -> dict[str, object]:
    raw_query = payload.get("query")
    assert isinstance(raw_query, dict)
    return _normalize_payload(raw_query)


@pytest.mark.anyio
async def test_get_real_price_default_limit_and_metadata(
    monkeypatch: pytest.MonkeyPatch,
    mcp_server: FastMCP,
) -> None:
    captured_kwargs: dict[str, Any] = {}
    count_call_count = 0

    async def fake_get_real_price(self: Any, **kwargs: Any) -> list[dict[str, object]]:  # noqa: ARG001
        captured_kwargs.update(kwargs)
        return [{"id": 1}, {"id": 2}]

    async def fake_get_real_price_total_count(self: Any, **kwargs: Any) -> int:  # noqa: ARG001
        nonlocal count_call_count
        count_call_count += 1
        return 2

    monkeypatch.setattr(
        price_tools.PriceService,
        "get_real_price",
        fake_get_real_price,
    )
    monkeypatch.setattr(
        price_tools.PriceService,
        "get_real_price_total_count",
        fake_get_real_price_total_count,
    )

    result = await mcp_server.call_tool("get_real_price", {"region_code": "11110"})
    payload = _extract_payload(result)
    query = _extract_query(payload)

    assert captured_kwargs["limit"] == 50
    assert query["limit"] == 50
    assert payload["count"] == 2
    assert payload["returned_count"] == 2
    assert payload["total_count"] == 2
    assert payload["has_more"] is False
    assert count_call_count == 0


@pytest.mark.anyio
async def test_get_real_price_limit_20_sets_has_more_when_total_exceeds_returned(
    monkeypatch: pytest.MonkeyPatch,
    mcp_server: FastMCP,
) -> None:
    captured_kwargs: dict[str, Any] = {}
    count_call_count = 0

    async def fake_get_real_price(self: Any, **kwargs: Any) -> list[dict[str, object]]:  # noqa: ARG001
        captured_kwargs.update(kwargs)
        return [{"id": index} for index in range(20)]

    async def fake_get_real_price_total_count(self: Any, **kwargs: Any) -> int:  # noqa: ARG001
        nonlocal count_call_count
        count_call_count += 1
        return 85

    monkeypatch.setattr(
        price_tools.PriceService,
        "get_real_price",
        fake_get_real_price,
    )
    monkeypatch.setattr(
        price_tools.PriceService,
        "get_real_price_total_count",
        fake_get_real_price_total_count,
    )

    result = await mcp_server.call_tool(
        "get_real_price",
        {"region_code": "11110", "limit": 20},
    )
    payload = _extract_payload(result)
    query = _extract_query(payload)
    returned_count_raw = payload["returned_count"]
    total_count_raw = payload["total_count"]
    count_raw = payload["count"]
    assert isinstance(returned_count_raw, int)
    assert isinstance(total_count_raw, int)
    assert isinstance(count_raw, int)
    returned_count = returned_count_raw
    total_count = total_count_raw

    assert captured_kwargs["limit"] == 20
    assert query["limit"] == 20
    assert count_raw == returned_count
    assert returned_count <= 20
    assert total_count > returned_count
    assert payload["has_more"] is True
    assert count_call_count == 1


@pytest.mark.anyio
async def test_get_real_price_limit_20_sets_has_more_false_when_total_equals_returned(
    monkeypatch: pytest.MonkeyPatch,
    mcp_server: FastMCP,
) -> None:
    captured_kwargs: dict[str, Any] = {}
    count_call_count = 0

    async def fake_get_real_price(self: Any, **kwargs: Any) -> list[dict[str, object]]:  # noqa: ARG001
        captured_kwargs.update(kwargs)
        return [{"id": index} for index in range(20)]

    async def fake_get_real_price_total_count(self: Any, **kwargs: Any) -> int:  # noqa: ARG001
        nonlocal count_call_count
        count_call_count += 1
        return 20

    monkeypatch.setattr(
        price_tools.PriceService,
        "get_real_price",
        fake_get_real_price,
    )
    monkeypatch.setattr(
        price_tools.PriceService,
        "get_real_price_total_count",
        fake_get_real_price_total_count,
    )

    result = await mcp_server.call_tool(
        "get_real_price",
        {"region_code": "11110", "limit": 20},
    )
    payload = _extract_payload(result)
    query = _extract_query(payload)

    assert captured_kwargs["limit"] == 20
    assert query["limit"] == 20
    assert payload["count"] == 20
    assert payload["returned_count"] == 20
    assert payload["total_count"] == 20
    assert payload["has_more"] is False
    assert count_call_count == 1


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("limit", "expected_message"),
    [
        (0, "limit must be greater than 0"),
        (201, "limit must be less than or equal to 200"),
    ],
)
async def test_get_real_price_rejects_invalid_limit(
    limit: int,
    expected_message: str,
    mcp_server: FastMCP,
) -> None:
    with pytest.raises(ToolError, match=expected_message):
        _ = await mcp_server.call_tool(
            "get_real_price",
            {"region_code": "11110", "limit": limit},
        )
