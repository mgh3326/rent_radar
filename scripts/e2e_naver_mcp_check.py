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

# Allow direct execution: `python scripts/e2e_naver_mcp_check.py ...`
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


@dataclass(frozen=True)
class CliArgs:
    seed_source: str
    seed_dong_prefix: str
    mcp_limit: int
    cleanup_scope: CleanupScope


def _normalize_payload(mapping: dict[object, object]) -> dict[str, object]:
    return {str(key): value for key, value in mapping.items()}


def _parse_args() -> CliArgs:
    parser = argparse.ArgumentParser(
        description="One-shot Naver seed -> MCP search_rent verification script."
    )
    _ = parser.add_argument(
        "--seed-source",
        default="naver_test_seed",
        help="Listing source name for test seed data (default: naver_test_seed)",
    )
    _ = parser.add_argument(
        "--seed-dong-prefix",
        default="NAVER_MCP_TEST",
        help="Prefix for deterministic dong filter value (default: NAVER_MCP_TEST)",
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
        required=True,
        help="Cleanup scope. Only `source_only` is supported.",
    )
    namespace = parser.parse_args()
    return CliArgs(
        seed_source=cast(str, namespace.seed_source),
        seed_dong_prefix=cast(str, namespace.seed_dong_prefix),
        mcp_limit=cast(int, namespace.mcp_limit),
        cleanup_scope=cast(CleanupScope, namespace.cleanup_scope),
    )


def _extract_mcp_payload(tool_result: object) -> dict[str, object]:
    if isinstance(tool_result, dict):
        return _normalize_payload(cast(dict[object, object], tool_result))
    if isinstance(tool_result, tuple):
        for part in cast(tuple[object, ...], tool_result):
            if isinstance(part, dict):
                return _normalize_payload(cast(dict[object, object], part))
            if isinstance(part, list) and part:
                first = cast(list[object], part)[0]
                maybe_text = getattr(first, "text", None)
                if isinstance(maybe_text, str):
                    try:
                        loaded_obj = cast(object, json.loads(maybe_text))
                    except json.JSONDecodeError as exc:
                        raise RuntimeError(
                            f"Failed to parse MCP text payload as JSON: {exc}"
                        ) from exc
                    if isinstance(loaded_obj, dict):
                        return _normalize_payload(
                            cast(dict[object, object], loaded_obj)
                        )
    raise RuntimeError("Failed to extract structured MCP payload from call result")


def _extract_count(payload: dict[str, object]) -> int:
    count_raw = payload.get("count")
    if isinstance(count_raw, int):
        return count_raw
    if isinstance(count_raw, float):
        return int(count_raw)
    items = payload.get("items")
    if isinstance(items, list):
        return len(cast(list[object], items))
    return 0


def _extract_items(payload: dict[str, object]) -> list[dict[str, object]]:
    items = payload.get("items")
    if not isinstance(items, list):
        raise RuntimeError("MCP payload has no list `items`")

    parsed_items: list[dict[str, object]] = []
    for raw_item in cast(list[object], items):
        if not isinstance(raw_item, dict):
            raise RuntimeError("MCP payload contains non-dict item")
        parsed_items.append(_normalize_payload(cast(dict[object, object], raw_item)))
    return parsed_items


def _build_seed_rows(
    seed_source: str, seed_dong: str, run_id: str
) -> list[ListingUpsert]:
    return [
        ListingUpsert(
            source=seed_source,
            source_id=f"{run_id}-seed-apt",
            property_type="apt",
            rent_type="jeonse",
            deposit=61000,
            monthly_rent=0,
            address=f"서울특별시 종로구 {seed_dong} 1",
            dong=seed_dong,
            detail_address=f"{seed_dong} 101호",
            area_m2=Decimal("84.20"),
            floor=9,
            total_floors=20,
            description="Naver MCP seed apt",
            latitude=Decimal("37.5721000"),
            longitude=Decimal("126.9791000"),
        ),
        ListingUpsert(
            source=seed_source,
            source_id=f"{run_id}-seed-villa",
            property_type="villa",
            rent_type="monthly",
            deposit=12000,
            monthly_rent=70,
            address=f"서울특별시 종로구 {seed_dong} 2",
            dong=seed_dong,
            detail_address=f"{seed_dong} 202호",
            area_m2=Decimal("52.35"),
            floor=4,
            total_floors=6,
            description="Naver MCP seed villa",
            latitude=Decimal("37.5725000"),
            longitude=Decimal("126.9789000"),
        ),
        ListingUpsert(
            source=seed_source,
            source_id=f"{run_id}-seed-officetel",
            property_type="officetel",
            rent_type="monthly",
            deposit=20000,
            monthly_rent=92,
            address=f"서울특별시 종로구 {seed_dong} 3",
            dong=seed_dong,
            detail_address=f"{seed_dong} 303호",
            area_m2=Decimal("41.10"),
            floor=11,
            total_floors=16,
            description="Naver MCP seed officetel",
            latitude=Decimal("37.5728000"),
            longitude=Decimal("126.9785000"),
        ),
    ]


async def _cleanup_seed_source(
    session: AsyncSession, seed_source: str
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


async def _count_seed_rows(
    session: AsyncSession, *, seed_source: str, seed_dong: str
) -> int:
    seed_row_count = (
        await session.execute(
            select(func.count(Listing.id)).where(
                Listing.source == seed_source,
                Listing.dong == seed_dong,
            )
        )
    ).scalar_one_or_none() or 0
    return int(seed_row_count)


def _summarize_call(payload: dict[str, object]) -> dict[str, object]:
    list_items = _extract_items(payload)
    return {
        "count": _extract_count(payload),
        "cache_hit": payload.get("cache_hit"),
        "sample_items": list_items[:5],
    }


def _check_items_quality(
    *,
    items: list[dict[str, object]],
    call_label: str,
    mcp_limit: int,
    seed_dong: str,
    seed_source: str,
) -> tuple[bool, list[str]]:
    failures: list[str] = []

    if len(items) > mcp_limit:
        failures.append(f"{call_label}_len(items) > limit")

    if any(str(item.get("source_id", "")).strip() == "" for item in items):
        failures.append(f"{call_label}_source_id_blank")

    if any(item.get("dong") != seed_dong for item in items):
        failures.append(f"{call_label}_dong_mismatch")

    if any(item.get("source") != seed_source for item in items):
        failures.append(f"{call_label}_source_mismatch")

    return (len(failures) == 0, failures)


async def _run(args: CliArgs) -> dict[str, object]:
    if args.mcp_limit <= 0:
        raise RuntimeError("--mcp-limit must be greater than 0")

    run_id = f"{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}_{uuid4().hex[:8]}"
    seed_dong = f"{args.seed_dong_prefix}_{run_id}"

    async with session_context() as session:
        cleanup_result = await _cleanup_seed_source(session, args.seed_source)

    failures: list[str] = []
    if cleanup_result["remaining_source_count"] != 0:
        failures.append("cleanup_remaining_source_count_nonzero")

    seed_rows = _build_seed_rows(args.seed_source, seed_dong, run_id)
    seed_row_count = len(seed_rows)
    async with session_context() as session:
        upsert_count = await upsert_listings(session, seed_rows)

    if upsert_count != seed_row_count:
        failures.append("upsert_count != seed_row_count")

    async with session_context() as session:
        observed_seed_row_count = await _count_seed_rows(
            session,
            seed_source=args.seed_source,
            seed_dong=seed_dong,
        )

    seed_validation_ok = observed_seed_row_count == seed_row_count
    if not seed_validation_ok:
        failures.append("seed_validation_count_mismatch")

    query = {"dong": seed_dong, "limit": args.mcp_limit}
    first_result = await mcp.call_tool("search_rent", query)
    second_result = await mcp.call_tool("search_rent", query)

    first_payload = _extract_mcp_payload(first_result)
    second_payload = _extract_mcp_payload(second_result)

    first_items = _extract_items(first_payload)
    second_items = _extract_items(second_payload)

    first_count = _extract_count(first_payload)
    second_count = _extract_count(second_payload)
    expected_count = min(seed_row_count, args.mcp_limit)
    first_call_count_matches_items = first_count == len(first_items)
    second_call_count_matches_items = second_count == len(second_items)
    counts_match = first_count == second_count

    first_call_items_quality_ok, first_call_item_failures = _check_items_quality(
        items=first_items,
        call_label="first_call",
        mcp_limit=args.mcp_limit,
        seed_dong=seed_dong,
        seed_source=args.seed_source,
    )
    second_call_items_quality_ok, second_call_item_failures = _check_items_quality(
        items=second_items,
        call_label="second_call",
        mcp_limit=args.mcp_limit,
        seed_dong=seed_dong,
        seed_source=args.seed_source,
    )

    if first_payload.get("cache_hit") is not False:
        failures.append("first_call_cache_hit != False")
    if second_payload.get("cache_hit") is not True:
        failures.append("second_call_cache_hit != True")
    if first_count <= 0:
        failures.append("mcp_count <= 0")
    if not first_call_count_matches_items:
        failures.append("first_count != len(first_items)")
    if not second_call_count_matches_items:
        failures.append("second_count != len(second_items)")
    if first_count != expected_count:
        failures.append("first_count != expected_count")
    if not counts_match:
        failures.append("second_count != first_count")
    failures.extend(first_call_item_failures)
    failures.extend(second_call_item_failures)

    report: dict[str, object] = {
        "status": "success" if not failures else "failure",
        "executed_at": datetime.now(UTC).isoformat(),
        "run_id": run_id,
        "seed_source": args.seed_source,
        "seed_dong": seed_dong,
        "seed_row_count": seed_row_count,
        "upsert_count": upsert_count,
        "seed_validation": {
            "observed": observed_seed_row_count,
            "expected": seed_row_count,
            "ok": seed_validation_ok,
        },
        "cleanup": cleanup_result,
        "mcp": {
            "tool": "search_rent",
            "query": query,
            "expected_count": expected_count,
            "first_call": _summarize_call(first_payload),
            "second_call": _summarize_call(second_payload),
            "first_call_count_matches_items": first_call_count_matches_items,
            "second_call_count_matches_items": second_call_count_matches_items,
            "first_call_items_quality_ok": first_call_items_quality_ok,
            "second_call_items_quality_ok": second_call_items_quality_ok,
            "counts_match": counts_match,
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
