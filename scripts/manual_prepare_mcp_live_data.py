from __future__ import annotations

# ruff: noqa: E402

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.config.region_codes import region_codes_to_district_names
from src.crawlers.zigbang import (
    DEFAULT_BASE_DELAY_SECONDS,
    DEFAULT_COOLDOWN_SECONDS,
    DEFAULT_COOLDOWN_THRESHOLD,
    DEFAULT_MAX_BACKOFF_SECONDS,
    DEFAULT_MAX_RETRIES,
    ZigbangCrawler,
)
from src.db.repositories import upsert_listings
from src.db.session import session_context

DEFAULT_REGION_CODES = "41135"
DEFAULT_PROPERTY_TYPES = "아파트"
DEFAULT_MAX_REGIONS = 1


@dataclass(frozen=True)
class CliArgs:
    region_codes: str
    property_types: str
    max_regions: int
    max_retries: int = DEFAULT_MAX_RETRIES
    base_delay_seconds: float = DEFAULT_BASE_DELAY_SECONDS
    max_backoff_seconds: float = DEFAULT_MAX_BACKOFF_SECONDS
    cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS
    cooldown_threshold: int = DEFAULT_COOLDOWN_THRESHOLD


def _parse_args() -> CliArgs:
    parser = argparse.ArgumentParser(
        description="Prepare live crawl data for manual Claude Desktop MCP checks."
    )
    _ = parser.add_argument(
        "--region-codes",
        default=DEFAULT_REGION_CODES,
        help="Comma-separated 5-digit region codes (default: 41135)",
    )
    _ = parser.add_argument(
        "--property-types",
        default=DEFAULT_PROPERTY_TYPES,
        help="Comma-separated Zigbang property types (default: 아파트)",
    )
    _ = parser.add_argument(
        "--max-regions",
        type=int,
        default=DEFAULT_MAX_REGIONS,
        help="Maximum number of resolved regions to crawl (default: 1)",
    )
    _ = parser.add_argument(
        "--max-retries",
        type=int,
        default=DEFAULT_MAX_RETRIES,
        help=f"HTTP 429 retry attempts (default: {DEFAULT_MAX_RETRIES})",
    )
    _ = parser.add_argument(
        "--base-delay-seconds",
        type=float,
        default=DEFAULT_BASE_DELAY_SECONDS,
        help=(
            f"Retry base backoff seconds (default: {DEFAULT_BASE_DELAY_SECONDS:.1f})"
        ),
    )
    _ = parser.add_argument(
        "--max-backoff-seconds",
        type=float,
        default=DEFAULT_MAX_BACKOFF_SECONDS,
        help=(
            f"Retry max backoff seconds (default: {DEFAULT_MAX_BACKOFF_SECONDS:.1f})"
        ),
    )
    _ = parser.add_argument(
        "--cooldown-seconds",
        type=float,
        default=DEFAULT_COOLDOWN_SECONDS,
        help=f"Cooldown sleep after repeated 429s (default: {DEFAULT_COOLDOWN_SECONDS:.1f})",
    )
    _ = parser.add_argument(
        "--cooldown-threshold",
        type=int,
        default=DEFAULT_COOLDOWN_THRESHOLD,
        help=f"Consecutive 429 threshold before cooldown (default: {DEFAULT_COOLDOWN_THRESHOLD})",
    )

    namespace = parser.parse_args()
    return CliArgs(
        region_codes=cast(str, namespace.region_codes),
        property_types=cast(str, namespace.property_types),
        max_regions=cast(int, namespace.max_regions),
        max_retries=cast(int, namespace.max_retries),
        base_delay_seconds=cast(float, namespace.base_delay_seconds),
        max_backoff_seconds=cast(float, namespace.max_backoff_seconds),
        cooldown_seconds=cast(float, namespace.cooldown_seconds),
        cooldown_threshold=cast(int, namespace.cooldown_threshold),
    )


def _split_csv(raw_value: str) -> list[str]:
    return [part.strip() for part in raw_value.split(",") if part.strip()]


async def _run(args: CliArgs) -> dict[str, object]:
    failures: list[str] = []
    warnings: list[str] = []

    region_codes = _split_csv(args.region_codes)
    property_types = _split_csv(args.property_types)
    if args.max_regions <= 0:
        failures.append("max_regions <= 0")
    if args.max_retries < 0:
        failures.append("max_retries < 0")
    if args.base_delay_seconds < 0:
        failures.append("base_delay_seconds < 0")
    if args.max_backoff_seconds < args.base_delay_seconds:
        failures.append("max_backoff_seconds < base_delay_seconds")
    if args.cooldown_seconds < 0:
        failures.append("cooldown_seconds < 0")
    if args.cooldown_threshold <= 0:
        failures.append("cooldown_threshold <= 0")

    region_names = region_codes_to_district_names(region_codes)
    if args.max_regions > 0:
        region_names = region_names[: args.max_regions]

    if not region_names:
        failures.append("region_names == 0")
    if not property_types:
        failures.append("property_types == 0")

    crawl_count = 0
    crawl_errors: list[str] = []
    crawl_metrics: dict[str, object] = {}
    upsert_count = 0

    if not failures:
        crawler = ZigbangCrawler(
            region_names=region_names,
            property_types=property_types,
            max_retries=args.max_retries,
            base_delay_seconds=args.base_delay_seconds,
            max_backoff_seconds=args.max_backoff_seconds,
            cooldown_seconds=args.cooldown_seconds,
            cooldown_threshold=args.cooldown_threshold,
        )
        crawl_result = await crawler.run()
        crawl_count = crawl_result.count
        crawl_errors = list(crawl_result.errors)
        crawl_metrics = dict(crawler.last_run_metrics)
        if crawl_errors:
            warnings.append("crawl_errors_present")

        async with session_context() as session:
            upsert_count = await upsert_listings(session, crawl_result.rows)

        if crawl_count <= 0:
            failures.append("crawl.count <= 0")
        if upsert_count <= 0:
            failures.append("upsert_count <= 0")

    report: dict[str, object] = {
        "status": "success" if not failures else "failure",
        "executed_at": datetime.now(UTC).isoformat(),
        "input": {
            "region_codes": args.region_codes,
            "property_types": args.property_types,
            "max_regions": args.max_regions,
            "max_retries": args.max_retries,
            "base_delay_seconds": args.base_delay_seconds,
            "max_backoff_seconds": args.max_backoff_seconds,
            "cooldown_seconds": args.cooldown_seconds,
            "cooldown_threshold": args.cooldown_threshold,
        },
        "crawl": {
            "region_codes": region_codes,
            "region_names": region_names,
            "property_types": property_types,
            "count": crawl_count,
            "errors": crawl_errors,
            "metrics": crawl_metrics,
        },
        "persistence": {
            "upsert_count": upsert_count,
        },
        "warnings": warnings,
        "failures": failures,
    }
    return report


async def _async_main() -> int:
    args = _parse_args()

    try:
        report = await _run(args)
    except Exception as exc:  # noqa: BLE001
        error_report = {
            "status": "failure",
            "executed_at": datetime.now(UTC).isoformat(),
            "crawl": {
                "count": 0,
            },
            "persistence": {
                "upsert_count": 0,
            },
            "failures": [str(exc)],
        }
        print(json.dumps(error_report, ensure_ascii=False, indent=2))
        return 1

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("status") == "success" else 1


def main() -> None:
    raise SystemExit(asyncio.run(_async_main()))


if __name__ == "__main__":
    main()
