"""Run a one-shot Zigbang -> DB -> MCP end-to-end check.

This script intentionally bypasses TaskIQ worker/scheduler and performs:
1) destructive reset (favorites, price_changes, listings),
2) direct Zigbang crawl,
3) direct DB upsert,
4) direct MCP tool call (`search_rent`),
5) strict success/failure gate checks.
"""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

# Allow direct execution: `python scripts/e2e_zigbang_mcp_check.py ...`
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.config.region_codes import is_valid_region_code, region_codes_to_district_names
from src.crawlers.zigbang import ZigbangCrawler, ZigbangSchemaMismatchError
from src.db.repositories import upsert_listings
from src.db.session import session_context
from src.mcp_server.server import mcp
from src.models.favorite import Favorite
from src.models.listing import Listing
from src.models.price_change import PriceChange


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="One-shot Zigbang -> DB -> MCP verification script."
    )
    parser.add_argument(
        "--region-code",
        default="11110",
        help="5-digit region code (default: 11110)",
    )
    parser.add_argument(
        "--property-types",
        default="아파트,빌라/연립,오피스텔",
        help="Comma-separated Zigbang property types (default: 아파트,빌라/연립,오피스텔)",
    )
    parser.add_argument(
        "--mcp-limit",
        type=int,
        default=20,
        help="`search_rent` MCP limit (default: 20)",
    )
    parser.add_argument(
        "--reset-scope",
        choices=["full"],
        required=True,
        help="Destructive reset scope. Only `full` is supported.",
    )
    parser.add_argument(
        "--confirm-reset",
        required=True,
        help="Must be exactly RESET_ALL to allow destructive reset.",
    )
    return parser.parse_args()


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, tuple):
        return [_json_safe(v) for v in value]
    return value


def _parse_property_types(raw: str) -> list[str]:
    return [part.strip() for part in raw.split(",") if part.strip()]


def _extract_crawl_metrics(crawler: ZigbangCrawler) -> dict[str, Any]:
    metrics = getattr(crawler, "last_run_metrics", {})
    if not isinstance(metrics, dict):
        return {
            "raw_count": 0,
            "parsed_count": 0,
            "invalid_count": 0,
            "schema_keys_sample": [],
            "source_keys_sample": [],
        }

    return {
        "raw_count": int(metrics.get("raw_count", 0)),
        "parsed_count": int(metrics.get("parsed_count", 0)),
        "invalid_count": int(metrics.get("invalid_count", 0)),
        "schema_keys_sample": metrics.get("schema_keys_sample", []),
        "source_keys_sample": metrics.get("source_keys_sample", []),
    }


async def _collect_snapshot(session: AsyncSession) -> dict[str, int]:
    listings_total = (
        await session.execute(select(func.count(Listing.id)))
    ).scalar_one_or_none() or 0
    favorites_total = (
        await session.execute(select(func.count(Favorite.id)))
    ).scalar_one_or_none() or 0
    price_changes_total = (
        await session.execute(select(func.count(PriceChange.id)))
    ).scalar_one_or_none() or 0
    zigbang_listings_total = (
        await session.execute(
            select(func.count(Listing.id)).where(Listing.source == "zigbang")
        )
    ).scalar_one_or_none() or 0
    return {
        "listings_total": int(listings_total),
        "favorites_total": int(favorites_total),
        "price_changes_total": int(price_changes_total),
        "zigbang_listings_total": int(zigbang_listings_total),
    }


async def _reset_all_tables(session: AsyncSession) -> None:
    # FK-safe order: favorites -> price_changes -> listings
    await session.execute(delete(Favorite))
    await session.execute(delete(PriceChange))
    await session.execute(delete(Listing))
    await session.commit()


def _extract_mcp_payload(tool_result: Any) -> tuple[dict[str, Any], str | None]:
    payload: dict[str, Any] | None = None
    text_payload: str | None = None

    if isinstance(tool_result, dict):
        payload = tool_result
    elif isinstance(tool_result, tuple):
        for part in tool_result:
            if isinstance(part, dict):
                payload = part
            elif isinstance(part, list) and part:
                first = part[0]
                maybe_text = getattr(first, "text", None)
                if isinstance(maybe_text, str):
                    text_payload = maybe_text

    if payload is None and text_payload is not None:
        try:
            loaded = json.loads(text_payload)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Failed to parse MCP text payload as JSON") from exc
        if isinstance(loaded, dict):
            payload = loaded

    if payload is None:
        raise RuntimeError("MCP `search_rent` did not return a structured payload")

    return payload, text_payload


def _extract_mcp_count(payload: dict[str, Any]) -> int:
    count_raw = payload.get("count")
    if isinstance(count_raw, int):
        return count_raw
    if isinstance(count_raw, float):
        return int(count_raw)

    items = payload.get("items")
    if isinstance(items, list):
        return len(items)
    return 0


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    if args.confirm_reset != "RESET_ALL":
        raise RuntimeError("Reset blocked: --confirm-reset must be exactly RESET_ALL")

    if args.mcp_limit <= 0:
        raise RuntimeError("--mcp-limit must be greater than 0")

    if not is_valid_region_code(args.region_code):
        raise RuntimeError(f"Invalid region code: {args.region_code}")

    property_types = _parse_property_types(args.property_types)
    if not property_types:
        raise RuntimeError("No property types provided")

    region_names = region_codes_to_district_names([args.region_code])
    if not region_names:
        raise RuntimeError(
            f"No district name resolved for region code {args.region_code}"
        )

    async with session_context() as session:
        initial_snapshot = await _collect_snapshot(session)
        await _reset_all_tables(session)
        pre_crawl_snapshot = await _collect_snapshot(session)

    if any(value != 0 for value in pre_crawl_snapshot.values()):
        raise RuntimeError(
            f"Reset verification failed; expected all zeros, got {pre_crawl_snapshot}"
        )

    crawler = ZigbangCrawler(
        region_names=region_names,
        region_codes=[args.region_code],
        property_types=property_types,
    )
    try:
        crawl_result = await crawler.run()
    except ZigbangSchemaMismatchError as exc:
        crawl_metrics = _extract_crawl_metrics(crawler)
        failure_report = {
            "status": "failure",
            "executed_at": datetime.now(UTC).isoformat(),
            "args": {
                "region_code": args.region_code,
                "property_types": property_types,
                "mcp_limit": args.mcp_limit,
                "reset_scope": args.reset_scope,
            },
            "resolved_region_names": region_names,
            "snapshots": {
                "initial": initial_snapshot,
                "pre_crawl": pre_crawl_snapshot,
                "post_crawl": pre_crawl_snapshot,
            },
            "crawl": {
                "source": "zigbang",
                "count": 0,
                "errors": [str(exc)],
                "sample_rows": [],
                **crawl_metrics,
            },
            "persistence": {
                "upsert_count": 0,
            },
            "mcp": {
                "tool": "search_rent",
                "count": 0,
                "sample_items": [],
            },
            "failures": ["schema_mismatch"],
        }
        return _json_safe(failure_report)

    crawl_metrics = _extract_crawl_metrics(crawler)

    sample_rows = [_json_safe(asdict(row)) for row in crawl_result.rows[:5]]

    async with session_context() as session:
        upsert_count = await upsert_listings(session, crawl_result.rows)
        post_snapshot = await _collect_snapshot(session)

    mcp_tool_result = await mcp.call_tool("search_rent", {"limit": args.mcp_limit})
    mcp_payload, _mcp_text = _extract_mcp_payload(mcp_tool_result)
    mcp_count = _extract_mcp_count(mcp_payload)
    mcp_items = mcp_payload.get("items")
    mcp_items_sample = _json_safe(mcp_items[:5]) if isinstance(mcp_items, list) else []

    failures: list[str] = []
    if crawl_result.errors:
        failures.append("crawl_errors_present")
    if crawl_result.count <= 0:
        failures.append("crawl_count <= 0")
    if upsert_count <= 0:
        failures.append("upsert_count <= 0")
    if post_snapshot["listings_total"] <= pre_crawl_snapshot["listings_total"]:
        failures.append("post_listings_total <= pre_listings_total")
    if mcp_count <= 0:
        failures.append("mcp_count <= 0")
    if any(
        isinstance(item, dict) and str(item.get("source_id", "")) == ""
        for item in mcp_items_sample
    ):
        failures.append("mcp_sample_contains_empty_source_id")

    report = {
        "status": "success" if not failures else "failure",
        "executed_at": datetime.now(UTC).isoformat(),
        "args": {
            "region_code": args.region_code,
            "property_types": property_types,
            "mcp_limit": args.mcp_limit,
            "reset_scope": args.reset_scope,
        },
        "resolved_region_names": region_names,
        "snapshots": {
            "initial": initial_snapshot,
            "pre_crawl": pre_crawl_snapshot,
            "post_crawl": post_snapshot,
        },
        "crawl": {
            "source": "zigbang",
            "count": crawl_result.count,
            "errors": crawl_result.errors,
            "sample_rows": sample_rows,
            **crawl_metrics,
        },
        "persistence": {
            "upsert_count": upsert_count,
        },
        "mcp": {
            "tool": "search_rent",
            "count": mcp_count,
            "sample_items": mcp_items_sample,
        },
    }
    if failures:
        report["failures"] = failures

    return _json_safe(report)


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
