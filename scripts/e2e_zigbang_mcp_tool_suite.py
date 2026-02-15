# ruff: noqa: E402

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal, cast
from uuid import uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.db.repositories import ListingUpsert, upsert_listings
from src.db.session import session_context
from src.mcp_server.server import mcp
from src.models.favorite import Favorite
from src.models.listing import Listing
from src.models.price_change import PriceChange


CleanupScope = Literal["source_only"]

_REQUIRED_STAGE4_TOOLS: tuple[str, ...] = (
    "search_rent",
    "add_favorite",
    "list_favorites",
    "compare_listings",
    "manage_favorites",
)
_RECOMMENDED_STAGE4_ALLOWLIST = (
    "search_rent,list_regions,search_regions,add_favorite,list_favorites,"
    "remove_favorite,manage_favorites,compare_listings"
)


@dataclass(frozen=True)
class CliArgs:
    seed_source: str
    seed_dong_prefix: str
    user_id_prefix: str
    mcp_limit: int
    cleanup_scope: CleanupScope


def _normalize_payload(mapping: dict[object, object]) -> dict[str, object]:
    return {str(key): value for key, value in mapping.items()}


def _parse_args() -> CliArgs:
    parser = argparse.ArgumentParser(
        description="One-shot Zigbang seed MCP tool-suite verification script."
    )
    _ = parser.add_argument(
        "--seed-source",
        default="zigbang_test_seed",
        help="Listing source name for test seed data (default: zigbang_test_seed)",
    )
    _ = parser.add_argument(
        "--seed-dong-prefix",
        default="ZIGBANG_MCP_TEST",
        help="Prefix for deterministic dong filter value (default: ZIGBANG_MCP_TEST)",
    )
    _ = parser.add_argument(
        "--user-id-prefix",
        default="zigbang_mcp_suite",
        help="Prefix for test user id used in favorite flow",
    )
    _ = parser.add_argument(
        "--mcp-limit",
        type=int,
        default=3,
        help="MCP search_rent limit (default: 3)",
    )
    _ = parser.add_argument(
        "--cleanup-scope",
        choices=["source_only"],
        default="source_only",
        help="Cleanup scope. Only `source_only` is supported.",
    )
    namespace = parser.parse_args()
    return CliArgs(
        seed_source=cast(str, namespace.seed_source),
        seed_dong_prefix=cast(str, namespace.seed_dong_prefix),
        user_id_prefix=cast(str, namespace.user_id_prefix),
        mcp_limit=cast(int, namespace.mcp_limit),
        cleanup_scope=cast(CleanupScope, namespace.cleanup_scope),
    )


def _extract_mcp_payload(tool_result: object) -> dict[str, object]:
    if isinstance(tool_result, dict):
        return _normalize_payload(tool_result)

    if isinstance(tool_result, tuple):
        for part in tool_result:
            if isinstance(part, dict):
                return _normalize_payload(part)

            if isinstance(part, list) and part:
                first = part[0]
                maybe_text = getattr(first, "text", None)
                if isinstance(maybe_text, str):
                    try:
                        loaded = json.loads(maybe_text)
                    except json.JSONDecodeError as exc:
                        raise RuntimeError(
                            f"Failed to parse MCP text payload as JSON: {exc}"
                        ) from exc
                    if isinstance(loaded, dict):
                        return _normalize_payload(loaded)

    raise RuntimeError("Failed to extract structured MCP payload from call result")


def _extract_count(payload: dict[str, object]) -> int:
    count_raw = payload.get("count")
    if isinstance(count_raw, int):
        return count_raw
    if isinstance(count_raw, float):
        return int(count_raw)
    items = payload.get("items")
    if isinstance(items, list):
        return len(items)
    return 0


def _extract_items(payload: dict[str, object]) -> list[dict[str, object]]:
    items = payload.get("items")
    if not isinstance(items, list):
        raise RuntimeError("MCP payload has no list `items`")

    normalized_items: list[dict[str, object]] = []
    for item in items:
        if not isinstance(item, dict):
            raise RuntimeError("MCP payload contains non-dict item")
        normalized_items.append(_normalize_payload(item))
    return normalized_items


def _extract_listing_ids(items: list[dict[str, object]]) -> list[int]:
    listing_ids: list[int] = []
    for item in items:
        listing_id = item.get("id")
        if isinstance(listing_id, int):
            listing_ids.append(listing_id)
    return listing_ids


def _build_seed_rows(
    seed_source: str,
    seed_dong: str,
    run_id: str,
) -> list[ListingUpsert]:
    return [
        ListingUpsert(
            source=seed_source,
            source_id=f"{run_id}-suite-apt",
            property_type="apt",
            rent_type="jeonse",
            deposit=63000,
            monthly_rent=0,
            address=f"서울특별시 종로구 {seed_dong} 1",
            dong=seed_dong,
            detail_address=f"{seed_dong} 101호",
            area_m2=Decimal("84.14"),
            floor=11,
            total_floors=22,
            description="Zigbang MCP suite seed apt",
            latitude=Decimal("37.5721100"),
            longitude=Decimal("126.9792100"),
        ),
        ListingUpsert(
            source=seed_source,
            source_id=f"{run_id}-suite-villa",
            property_type="villa",
            rent_type="monthly",
            deposit=14000,
            monthly_rent=63,
            address=f"서울특별시 종로구 {seed_dong} 2",
            dong=seed_dong,
            detail_address=f"{seed_dong} 202호",
            area_m2=Decimal("55.50"),
            floor=4,
            total_floors=6,
            description="Zigbang MCP suite seed villa",
            latitude=Decimal("37.5724200"),
            longitude=Decimal("126.9789200"),
        ),
        ListingUpsert(
            source=seed_source,
            source_id=f"{run_id}-suite-officetel",
            property_type="officetel",
            rent_type="monthly",
            deposit=23000,
            monthly_rent=90,
            address=f"서울특별시 종로구 {seed_dong} 3",
            dong=seed_dong,
            detail_address=f"{seed_dong} 303호",
            area_m2=Decimal("42.60"),
            floor=9,
            total_floors=15,
            description="Zigbang MCP suite seed officetel",
            latitude=Decimal("37.5727300"),
            longitude=Decimal("126.9786300"),
        ),
    ]


async def _cleanup_seed_source(
    session: AsyncSession,
    seed_source: str,
) -> dict[str, int]:
    listing_ids_result = await session.execute(
        select(Listing.id).where(Listing.source == seed_source)
    )
    listing_ids = list(listing_ids_result.scalars().all())

    favorites_deleted = 0
    price_changes_deleted = 0
    if listing_ids:
        favorites_deleted = (
            await session.execute(
                select(func.count(Favorite.id)).where(
                    Favorite.listing_id.in_(listing_ids)
                )
            )
        ).scalar_one_or_none() or 0
        price_changes_deleted = (
            await session.execute(
                select(func.count(PriceChange.id)).where(
                    PriceChange.listing_id.in_(listing_ids)
                )
            )
        ).scalar_one_or_none() or 0

        _ = await session.execute(
            delete(Favorite).where(Favorite.listing_id.in_(listing_ids))
        )
        _ = await session.execute(
            delete(PriceChange).where(PriceChange.listing_id.in_(listing_ids))
        )

    _ = await session.execute(delete(Listing).where(Listing.source == seed_source))
    listings_deleted = len(listing_ids)
    await session.commit()

    remaining_source_count = (
        await session.execute(
            select(func.count(Listing.id)).where(Listing.source == seed_source)
        )
    ).scalar_one_or_none() or 0

    return {
        "seed_listing_ids_count": len(listing_ids),
        "favorites_deleted": int(favorites_deleted),
        "price_changes_deleted": int(price_changes_deleted),
        "listings_deleted": listings_deleted,
        "remaining_source_count": int(remaining_source_count),
    }


def _summarize_search_call(payload: dict[str, object]) -> dict[str, object]:
    items = _extract_items(payload)
    return {
        "count": _extract_count(payload),
        "cache_hit": payload.get("cache_hit"),
        "sample_items": items[:5],
    }


def _search_items_quality_ok(
    *,
    items: list[dict[str, object]],
    seed_source: str,
    seed_dong: str,
    mcp_limit: int,
) -> bool:
    return (
        len(items) <= mcp_limit
        and all(str(item.get("source_id", "")).strip() != "" for item in items)
        and all(item.get("source") == seed_source for item in items)
        and all(item.get("dong") == seed_dong for item in items)
    )


async def _assert_required_tools_available() -> None:
    registered_tools = await mcp.list_tools()
    available_tool_names = {
        str(getattr(tool, "name", "")).strip()
        for tool in registered_tools
        if str(getattr(tool, "name", "")).strip()
    }
    missing_tools = [
        tool_name
        for tool_name in _REQUIRED_STAGE4_TOOLS
        if tool_name not in available_tool_names
    ]

    if missing_tools:
        missing = ", ".join(missing_tools)
        raise RuntimeError(
            f"Required Stage 4 MCP tools are missing before execution: {missing}. "
            + f"Recommended MCP_ENABLED_TOOLS={_RECOMMENDED_STAGE4_ALLOWLIST}"
        )


async def _run(args: CliArgs) -> dict[str, object]:
    if args.mcp_limit <= 0:
        raise RuntimeError("--mcp-limit must be greater than 0")

    await _assert_required_tools_available()

    run_id = f"{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}_{uuid4().hex[:8]}"
    seed_dong = f"{args.seed_dong_prefix}_{run_id}"
    user_id = f"{args.user_id_prefix}_{run_id}"

    async with session_context() as session:
        cleanup_result = await _cleanup_seed_source(session, args.seed_source)

    failures: list[str] = []
    if cleanup_result["remaining_source_count"] != 0:
        failures.append("cleanup_remaining_source_count_nonzero")

    seed_rows = _build_seed_rows(args.seed_source, seed_dong, run_id)
    async with session_context() as session:
        upsert_count = await upsert_listings(session, seed_rows)

    if upsert_count <= 0:
        failures.append("upsert_count <= 0")

    search_query = {"dong": seed_dong, "limit": args.mcp_limit}
    first_search_result = await mcp.call_tool("search_rent", search_query)
    second_search_result = await mcp.call_tool("search_rent", search_query)

    first_search_payload = _extract_mcp_payload(first_search_result)
    second_search_payload = _extract_mcp_payload(second_search_result)

    first_search_items = _extract_items(first_search_payload)
    second_search_items = _extract_items(second_search_payload)
    first_search_count = _extract_count(first_search_payload)
    second_search_count = _extract_count(second_search_payload)
    expected_search_count = min(len(seed_rows), args.mcp_limit)

    first_count_matches_items = first_search_count == len(first_search_items)
    second_count_matches_items = second_search_count == len(second_search_items)
    counts_match = first_search_count == second_search_count

    first_quality_ok = _search_items_quality_ok(
        items=first_search_items,
        seed_source=args.seed_source,
        seed_dong=seed_dong,
        mcp_limit=args.mcp_limit,
    )
    second_quality_ok = _search_items_quality_ok(
        items=second_search_items,
        seed_source=args.seed_source,
        seed_dong=seed_dong,
        mcp_limit=args.mcp_limit,
    )

    if first_search_payload.get("cache_hit") is not False:
        failures.append("search_first_cache_hit != False")
    if second_search_payload.get("cache_hit") is not True:
        failures.append("search_second_cache_hit != True")
    if first_search_count <= 0:
        failures.append("search_first_count <= 0")
    if first_search_count != expected_search_count:
        failures.append("search_first_count != expected_search_count")
    if not first_count_matches_items:
        failures.append("search_first_count != len(items)")
    if not second_count_matches_items:
        failures.append("search_second_count != len(items)")
    if not counts_match:
        failures.append("search_first_count != search_second_count")
    if not first_quality_ok:
        failures.append("search_first_items_quality_failed")
    if not second_quality_ok:
        failures.append("search_second_items_quality_failed")

    listing_ids = _extract_listing_ids(first_search_items)
    if len(listing_ids) < 2:
        failures.append("search_listing_ids_count < 2")
    compare_listing_ids = listing_ids[:2]

    favorite_add_payload: dict[str, object] = {}
    favorites_list_payload: dict[str, object] = {}
    compare_success_payload: dict[str, object] = {}
    not_found_payload: dict[str, object] = {}
    compare_one_payload: dict[str, object] = {}
    compare_eleven_payload: dict[str, object] = {}
    invalid_action_payload: dict[str, object] = {}

    if compare_listing_ids:
        favorite_add_result = await mcp.call_tool(
            "add_favorite",
            {"user_id": user_id, "listing_id": compare_listing_ids[0]},
        )
        favorite_add_payload = _extract_mcp_payload(favorite_add_result)
        if favorite_add_payload.get("status") != "added":
            failures.append("favorite_add_status != added")

        favorites_list_result = await mcp.call_tool(
            "list_favorites",
            {"user_id": user_id, "limit": 10},
        )
        favorites_list_payload = _extract_mcp_payload(favorites_list_result)
        list_items_raw = favorites_list_payload.get("items")
        list_count = favorites_list_payload.get("count")
        if not isinstance(list_items_raw, list):
            failures.append("favorite_list_items_not_list")
            list_items: list[object] = []
        else:
            list_items = list_items_raw
            if list_count != len(list_items_raw):
                failures.append("favorite_list_count != len(items)")
            if len(list_items_raw) <= 0:
                failures.append("favorite_list_count <= 0")

        if list_items:
            first_item = list_items[0]
            if not isinstance(first_item, dict):
                failures.append("favorite_first_item_not_dict")
            elif first_item.get("listing_id") != compare_listing_ids[0]:
                failures.append("favorite_first_listing_id_mismatch")

    if len(compare_listing_ids) == 2:
        compare_success_result = await mcp.call_tool(
            "compare_listings",
            {"listing_ids": compare_listing_ids},
        )
        compare_success_payload = _extract_mcp_payload(compare_success_result)
        if compare_success_payload.get("status") != "success":
            failures.append("compare_success_status != success")

        listing_count = compare_success_payload.get("listing_count")
        if listing_count != 2:
            failures.append("compare_success_listing_count != 2")

        comparisons_raw = compare_success_payload.get("comparisons")
        if not isinstance(comparisons_raw, list):
            failures.append("compare_success_comparisons_not_list")
            comparisons: list[object] = []
        else:
            comparisons = comparisons_raw
            if len(comparisons_raw) != 2:
                failures.append("compare_success_len(comparisons) != 2")

        if not isinstance(compare_success_payload.get("summary"), dict):
            failures.append("compare_success_summary_not_dict")

        for comparison in comparisons:
            if not isinstance(comparison, dict):
                failures.append("compare_success_contains_non_dict_comparison")
                continue

            if "market_avg_deposit" not in comparison:
                failures.append("compare_success_market_avg_deposit_missing")
            if "market_sample_count" not in comparison:
                failures.append("compare_success_market_sample_count_missing")

            market_avg = comparison.get("market_avg_deposit")
            if market_avg is not None and not isinstance(market_avg, (int, float)):
                failures.append("compare_success_market_avg_deposit_invalid_type")

            market_sample_count = comparison.get("market_sample_count")
            if not isinstance(market_sample_count, int) or market_sample_count < 0:
                failures.append("compare_success_market_sample_count_invalid")

    compare_one_result = await mcp.call_tool(
        "compare_listings",
        {"listing_ids": compare_listing_ids[:1] if compare_listing_ids else [1]},
    )
    compare_one_payload = _extract_mcp_payload(compare_one_result)
    if compare_one_payload.get("status") != "error":
        failures.append("compare_one_status != error")
    if (
        compare_one_payload.get("message")
        != "At least 2 listings required for comparison"
    ):
        failures.append("compare_one_message_mismatch")

    compare_eleven_ids = [
        compare_listing_ids[0] if compare_listing_ids else 1,
    ] * 11
    compare_eleven_result = await mcp.call_tool(
        "compare_listings",
        {"listing_ids": compare_eleven_ids},
    )
    compare_eleven_payload = _extract_mcp_payload(compare_eleven_result)
    if compare_eleven_payload.get("status") != "error":
        failures.append("compare_eleven_status != error")
    if compare_eleven_payload.get("message") != "Maximum 10 listings can be compared":
        failures.append("compare_eleven_message_mismatch")

    invalid_action_result = await mcp.call_tool(
        "manage_favorites",
        {"action": "invalid", "user_id": user_id},
    )
    invalid_action_payload = _extract_mcp_payload(invalid_action_result)
    if invalid_action_payload.get("success") is not False:
        failures.append("manage_invalid_success != False")
    invalid_action_error = str(invalid_action_payload.get("error", "")).lower()
    if "unknown action" not in invalid_action_error:
        failures.append("manage_invalid_error_message_mismatch")

    not_found_listing_id = 2147483647
    not_found_result = await mcp.call_tool(
        "add_favorite",
        {"user_id": user_id, "listing_id": not_found_listing_id},
    )
    not_found_payload = _extract_mcp_payload(not_found_result)
    if not_found_payload.get("status") != "not_found":
        failures.append("add_not_found_status != not_found")
    if "not found" not in str(not_found_payload.get("message", "")).lower():
        failures.append("add_not_found_message_mismatch")

    report: dict[str, object] = {
        "status": "success" if not failures else "failure",
        "executed_at": datetime.now(UTC).isoformat(),
        "run_id": run_id,
        "seed_source": args.seed_source,
        "seed_dong": seed_dong,
        "user_id": user_id,
        "upsert_count": upsert_count,
        "cleanup": cleanup_result,
        "flow": {
            "search_query": search_query,
            "search_expected_count": expected_search_count,
            "search_first_call": _summarize_search_call(first_search_payload),
            "search_second_call": _summarize_search_call(second_search_payload),
            "search_listing_ids": listing_ids,
            "favorite_add": favorite_add_payload,
            "favorites_list": favorites_list_payload,
            "compare_success": compare_success_payload,
        },
        "contract_checks": {
            "listing_not_found": not_found_payload,
            "compare_one": compare_one_payload,
            "compare_eleven": compare_eleven_payload,
            "invalid_action": invalid_action_payload,
        },
    }

    if failures:
        report["failures"] = failures
    return report


async def _async_main() -> int:
    args = _parse_args()
    try:
        report = await _run(args)
    except Exception as exc:  # noqa: BLE001
        error_report = {
            "status": "failure",
            "executed_at": datetime.now(UTC).isoformat(),
            "error": str(exc),
        }
        print(json.dumps(error_report, ensure_ascii=False, indent=2))
        return 1

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("status") == "success" else 1


def main() -> None:
    raise SystemExit(asyncio.run(_async_main()))


if __name__ == "__main__":
    main()
