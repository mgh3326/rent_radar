from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import cast

import pytest

from scripts import e2e_zigbang_mcp_tool_suite as zigbang_suite


_DEFAULT_REQUIRED_STAGE4_TOOLS = [
    "search_rent",
    "add_favorite",
    "list_favorites",
    "compare_listings",
    "manage_favorites",
]


def _make_args(mcp_limit: int = 3) -> zigbang_suite.CliArgs:
    return zigbang_suite.CliArgs(
        seed_source="zigbang_test_seed",
        seed_dong_prefix="ZIGBANG_MCP_TEST",
        user_id_prefix="zigbang_mcp_suite",
        mcp_limit=mcp_limit,
        cleanup_scope="source_only",
    )


def _build_search_items(source: str, dong: str, limit: int) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = [
        {
            "id": 101,
            "source": source,
            "source_id": "seed-101",
            "dong": dong,
        },
        {
            "id": 102,
            "source": source,
            "source_id": "seed-102",
            "dong": dong,
        },
        {
            "id": 103,
            "source": source,
            "source_id": "seed-103",
            "dong": dong,
        },
    ]
    return rows[:limit]


async def _run_script(args: zigbang_suite.CliArgs) -> dict[str, object]:
    run_impl = cast(
        Callable[[zigbang_suite.CliArgs], Awaitable[dict[str, object]]],
        getattr(zigbang_suite, "_run"),
    )
    return await run_impl(args)


def _default_call_tool_builder(
    args: zigbang_suite.CliArgs,
) -> Callable[[str, dict[str, object]], Awaitable[dict[str, object]]]:
    search_calls = {"count": 0}

    async def _call_tool(
        tool_name: str,
        payload: dict[str, object],
    ) -> dict[str, object]:
        if tool_name == "search_rent":
            search_calls["count"] += 1
            limit = cast(int, payload["limit"])
            dong = cast(str, payload["dong"])
            items = _build_search_items(args.seed_source, dong, limit)
            return {
                "count": len(items),
                "items": items,
                "cache_hit": search_calls["count"] == 2,
            }

        if tool_name == "add_favorite":
            listing_id = cast(int, payload["listing_id"])
            if listing_id == 2147483647:
                return {
                    "user_id": payload["user_id"],
                    "listing_id": listing_id,
                    "status": "not_found",
                    "message": "Listing not found or inactive",
                }

            return {
                "user_id": payload["user_id"],
                "listing_id": listing_id,
                "status": "added",
                "message": "Listing added to favorites",
            }

        if tool_name == "list_favorites":
            return {
                "user_id": payload["user_id"],
                "count": 1,
                "items": [
                    {
                        "favorite_id": 1,
                        "user_id": payload["user_id"],
                        "listing_id": 101,
                        "listing": {"id": 101},
                    }
                ],
            }

        if tool_name == "compare_listings":
            listing_ids = cast(list[int], payload["listing_ids"])
            if len(listing_ids) == 1:
                return {
                    "status": "error",
                    "message": "At least 2 listings required for comparison",
                    "comparisons": [],
                }

            if len(listing_ids) > 10:
                return {
                    "status": "error",
                    "message": "Maximum 10 listings can be compared",
                    "comparisons": [],
                }

            return {
                "status": "success",
                "listing_count": 2,
                "comparisons": [
                    {
                        "id": 101,
                        "deposit": 63000,
                        "market_avg_deposit": None,
                        "market_sample_count": 0,
                    },
                    {
                        "id": 102,
                        "deposit": 14000,
                        "market_avg_deposit": None,
                        "market_sample_count": 0,
                    },
                ],
                "summary": {
                    "min_deposit": 14000,
                    "max_deposit": 63000,
                    "avg_deposit": 38500,
                },
            }

        if tool_name == "manage_favorites":
            return {
                "success": False,
                "error": "Unknown action: invalid. Use 'add', 'remove', or 'list'.",
            }

        raise AssertionError(f"unexpected tool call: {tool_name}")

    return _call_tool


def _patch_run_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    *,
    args: zigbang_suite.CliArgs,
    cleanup_remaining_source_count: int = 0,
    upsert_count: int = 3,
    available_tools: list[str] | None = None,
    call_tool_impl: Callable[[str, dict[str, object]], Awaitable[dict[str, object]]]
    | None = None,
) -> None:
    @asynccontextmanager
    async def fake_session_context():
        yield object()

    async def fake_cleanup_seed_source(
        _session: object,
        seed_source: str,
    ) -> dict[str, int]:
        assert seed_source == args.seed_source
        return {
            "seed_listing_ids_count": 0,
            "favorites_deleted": 0,
            "price_changes_deleted": 0,
            "listings_deleted": 0,
            "remaining_source_count": cleanup_remaining_source_count,
        }

    async def fake_upsert_listings(_session: object, rows: list[object]) -> int:
        assert len(rows) == 3
        return upsert_count

    async def fake_list_tools() -> list[SimpleNamespace]:
        tool_names = available_tools or _DEFAULT_REQUIRED_STAGE4_TOOLS
        return [SimpleNamespace(name=tool_name) for tool_name in tool_names]

    effective_call_tool = call_tool_impl or _default_call_tool_builder(args)

    monkeypatch.setattr(
        "scripts.e2e_zigbang_mcp_tool_suite.session_context",
        fake_session_context,
    )
    monkeypatch.setattr(
        "scripts.e2e_zigbang_mcp_tool_suite._cleanup_seed_source",
        fake_cleanup_seed_source,
    )
    monkeypatch.setattr(
        "scripts.e2e_zigbang_mcp_tool_suite.upsert_listings",
        fake_upsert_listings,
    )
    monkeypatch.setattr(
        "scripts.e2e_zigbang_mcp_tool_suite.mcp.call_tool",
        effective_call_tool,
    )
    monkeypatch.setattr(
        "scripts.e2e_zigbang_mcp_tool_suite.mcp.list_tools",
        fake_list_tools,
    )


@pytest.mark.anyio
async def test_run_success_contract_suite(monkeypatch: pytest.MonkeyPatch) -> None:
    args = _make_args(3)
    _patch_run_dependencies(monkeypatch, args=args)

    report = await _run_script(args)

    assert report["status"] == "success"
    assert report["upsert_count"] == 3
    flow = cast(dict[str, object], report["flow"])
    contract_checks = cast(dict[str, object], report["contract_checks"])
    assert cast(dict[str, object], flow["favorite_add"])["status"] == "added"
    assert cast(dict[str, object], flow["compare_success"])["status"] == "success"
    assert "listing_not_found" in contract_checks
    assert "compare_one" in contract_checks
    assert "compare_eleven" in contract_checks
    assert "invalid_action" in contract_checks


@pytest.mark.anyio
async def test_run_failure_when_upsert_count_non_positive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = _make_args(3)
    _patch_run_dependencies(monkeypatch, args=args, upsert_count=0)

    report = await _run_script(args)

    assert report["status"] == "failure"
    failures = cast(list[object], report["failures"])
    assert "upsert_count <= 0" in failures


@pytest.mark.anyio
async def test_run_failure_when_search_cache_contract_breaks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = _make_args(3)
    default_call_tool = _default_call_tool_builder(args)

    async def broken_cache_call_tool(
        tool_name: str,
        payload: dict[str, object],
    ) -> dict[str, object]:
        response = await default_call_tool(tool_name, payload)
        if tool_name == "search_rent":
            response["cache_hit"] = True
        return response

    _patch_run_dependencies(
        monkeypatch, args=args, call_tool_impl=broken_cache_call_tool
    )

    report = await _run_script(args)

    assert report["status"] == "failure"
    failures = cast(list[object], report["failures"])
    assert "search_first_cache_hit != False" in failures


@pytest.mark.anyio
async def test_run_failure_when_compare_success_contract_breaks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = _make_args(3)
    default_call_tool = _default_call_tool_builder(args)

    async def broken_compare_call_tool(
        tool_name: str,
        payload: dict[str, object],
    ) -> dict[str, object]:
        if tool_name == "compare_listings":
            listing_ids = cast(list[int], payload["listing_ids"])
            if len(listing_ids) == 2:
                return {
                    "status": "partial",
                    "listing_count": 2,
                    "comparisons": [],
                    "summary": {},
                }
        return await default_call_tool(tool_name, payload)

    _patch_run_dependencies(
        monkeypatch,
        args=args,
        call_tool_impl=broken_compare_call_tool,
    )

    report = await _run_script(args)

    assert report["status"] == "failure"
    failures = cast(list[object], report["failures"])
    assert "compare_success_status != success" in failures


@pytest.mark.anyio
async def test_run_failure_when_listing_not_found_contract_breaks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = _make_args(3)
    default_call_tool = _default_call_tool_builder(args)

    async def broken_not_found_call_tool(
        tool_name: str,
        payload: dict[str, object],
    ) -> dict[str, object]:
        if (
            tool_name == "add_favorite"
            and cast(int, payload["listing_id"]) == 2147483647
        ):
            return {
                "user_id": payload["user_id"],
                "listing_id": payload["listing_id"],
                "status": "added",
                "message": "Listing added to favorites",
            }
        return await default_call_tool(tool_name, payload)

    _patch_run_dependencies(
        monkeypatch,
        args=args,
        call_tool_impl=broken_not_found_call_tool,
    )

    report = await _run_script(args)

    assert report["status"] == "failure"
    failures = cast(list[object], report["failures"])
    assert "add_not_found_status != not_found" in failures
    assert "add_not_found_message_mismatch" in failures


@pytest.mark.anyio
async def test_run_failure_when_compare_one_message_contract_breaks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = _make_args(3)
    default_call_tool = _default_call_tool_builder(args)

    async def broken_compare_one_message_call_tool(
        tool_name: str,
        payload: dict[str, object],
    ) -> dict[str, object]:
        if tool_name == "compare_listings":
            listing_ids = cast(list[int], payload["listing_ids"])
            if len(listing_ids) == 1:
                return {
                    "status": "error",
                    "message": "Need at least 2 listings",
                    "comparisons": [],
                }
        return await default_call_tool(tool_name, payload)

    _patch_run_dependencies(
        monkeypatch,
        args=args,
        call_tool_impl=broken_compare_one_message_call_tool,
    )

    report = await _run_script(args)

    assert report["status"] == "failure"
    failures = cast(list[object], report["failures"])
    assert "compare_one_message_mismatch" in failures


@pytest.mark.anyio
async def test_run_failure_when_compare_eleven_contract_breaks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = _make_args(3)
    default_call_tool = _default_call_tool_builder(args)

    async def broken_compare_eleven_call_tool(
        tool_name: str,
        payload: dict[str, object],
    ) -> dict[str, object]:
        if tool_name == "compare_listings":
            listing_ids = cast(list[int], payload["listing_ids"])
            if len(listing_ids) > 10:
                return {
                    "status": "success",
                    "message": "Comparison accepted",
                    "comparisons": [],
                }
        return await default_call_tool(tool_name, payload)

    _patch_run_dependencies(
        monkeypatch,
        args=args,
        call_tool_impl=broken_compare_eleven_call_tool,
    )

    report = await _run_script(args)

    assert report["status"] == "failure"
    failures = cast(list[object], report["failures"])
    assert "compare_eleven_status != error" in failures
    assert "compare_eleven_message_mismatch" in failures


@pytest.mark.anyio
async def test_run_failure_when_invalid_action_contract_breaks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = _make_args(3)
    default_call_tool = _default_call_tool_builder(args)

    async def broken_invalid_action_call_tool(
        tool_name: str,
        payload: dict[str, object],
    ) -> dict[str, object]:
        if tool_name == "manage_favorites":
            return {"success": True, "error": ""}
        return await default_call_tool(tool_name, payload)

    _patch_run_dependencies(
        monkeypatch,
        args=args,
        call_tool_impl=broken_invalid_action_call_tool,
    )

    report = await _run_script(args)

    assert report["status"] == "failure"
    failures = cast(list[object], report["failures"])
    assert "manage_invalid_success != False" in failures


@pytest.mark.anyio
async def test_run_raises_before_db_when_required_tools_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = _make_args(3)
    cleanup_called = {"value": False}
    upsert_called = {"value": False}

    @asynccontextmanager
    async def fake_session_context():
        yield object()

    async def fake_cleanup_seed_source(
        _session: object,
        _seed_source: str,
    ) -> dict[str, int]:
        cleanup_called["value"] = True
        return {
            "seed_listing_ids_count": 0,
            "favorites_deleted": 0,
            "price_changes_deleted": 0,
            "listings_deleted": 0,
            "remaining_source_count": 0,
        }

    async def fake_upsert_listings(_session: object, _rows: list[object]) -> int:
        upsert_called["value"] = True
        return 3

    async def fake_list_tools() -> list[SimpleNamespace]:
        return [SimpleNamespace(name="search_rent")]

    monkeypatch.setattr(
        "scripts.e2e_zigbang_mcp_tool_suite.session_context",
        fake_session_context,
    )
    monkeypatch.setattr(
        "scripts.e2e_zigbang_mcp_tool_suite._cleanup_seed_source",
        fake_cleanup_seed_source,
    )
    monkeypatch.setattr(
        "scripts.e2e_zigbang_mcp_tool_suite.upsert_listings",
        fake_upsert_listings,
    )
    monkeypatch.setattr(
        "scripts.e2e_zigbang_mcp_tool_suite.mcp.list_tools",
        fake_list_tools,
    )

    with pytest.raises(RuntimeError, match="Required Stage 4 MCP tools are missing"):
        _ = await _run_script(args)

    assert cleanup_called["value"] is False
    assert upsert_called["value"] is False


@pytest.mark.anyio
async def test_run_raises_when_mcp_limit_not_positive() -> None:
    with pytest.raises(RuntimeError, match="--mcp-limit must be greater than 0"):
        _ = await _run_script(_make_args(0))
