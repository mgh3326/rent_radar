from __future__ import annotations

# ruff: noqa: E402

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import cast

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.db.repositories import ListingUpsert, upsert_listings
from src.db.session import session_context
from src.models.favorite import Favorite
from src.models.listing import Listing
from src.models.price_change import PriceChange
from src.cache import build_search_cache_key, cache_delete

SEED_SOURCE = "manual_test_seed"
_CACHE_CLEAR_REGION_CODES = ("41135", "11680", "11110")
_CACHE_CLEAR_LIMITS = (3, 20, 50)


@dataclass(frozen=True)
class CliArgs:
    cleanup_source_only: bool
    clear_cache: bool


def _parse_args() -> CliArgs:
    parser = argparse.ArgumentParser(
        description="Manual seed for MCP region filtering checks."
    )
    _ = parser.add_argument(
        "--cleanup-source-only",
        action="store_true",
        help="Delete rows that belong to source='manual_test_seed' before reseeding.",
    )
    parser.set_defaults(clear_cache=True)
    _ = parser.add_argument(
        "--clear-cache",
        dest="clear_cache",
        action="store_true",
        help="Clear `search_rent(region_code=..., property_type=apt)` cache keys.",
    )
    _ = parser.add_argument(
        "--no-clear-cache",
        dest="clear_cache",
        action="store_false",
        help="Do not clear search cache keys after seeding.",
    )
    namespace = parser.parse_args()
    return CliArgs(
        cleanup_source_only=cast(bool, namespace.cleanup_source_only),
        clear_cache=cast(bool, namespace.clear_cache),
    )


def _build_seed_rows() -> list[ListingUpsert]:
    return [
        ListingUpsert(
            source=SEED_SOURCE,
            source_id="manual-seed-41135-apt-1",
            property_type="apt",
            rent_type="jeonse",
            deposit=65000,
            monthly_rent=0,
            address="경기도 성남시분당구 정자동 101",
            dong="성남시분당구",
            detail_address="분당구 정자동 101-1001",
            area_m2=Decimal("84.50"),
            floor=10,
            total_floors=20,
            description="manual region seed 41135",
            latitude=Decimal("37.3615000"),
            longitude=Decimal("127.1117000"),
        ),
        ListingUpsert(
            source=SEED_SOURCE,
            source_id="manual-seed-11680-apt-1",
            property_type="apt",
            rent_type="monthly",
            deposit=30000,
            monthly_rent=120,
            address="서울특별시 강남구 역삼동 202",
            dong="강남구",
            detail_address="강남구 역삼동 202-1201",
            area_m2=Decimal("59.70"),
            floor=12,
            total_floors=30,
            description="manual region seed 11680",
            latitude=Decimal("37.5008000"),
            longitude=Decimal("127.0365000"),
        ),
        ListingUpsert(
            source=SEED_SOURCE,
            source_id="manual-seed-11680-apt-2",
            property_type="apt",
            rent_type="monthly",
            deposit=45000,
            monthly_rent=150,
            address="서울특별시 강남구 역삼동 404",
            dong="역삼동",
            detail_address="강남구 역삼동 404-1902",
            area_m2=Decimal("74.30"),
            floor=19,
            total_floors=25,
            description="manual region seed 11680 naver-style dong",
            latitude=Decimal("37.5002000"),
            longitude=Decimal("127.0371000"),
        ),
        ListingUpsert(
            source=SEED_SOURCE,
            source_id="manual-seed-11110-apt-1",
            property_type="apt",
            rent_type="jeonse",
            deposit=52000,
            monthly_rent=0,
            address="서울특별시 종로구 사직동 303",
            dong="종로구",
            detail_address="종로구 사직동 303-801",
            area_m2=Decimal("74.10"),
            floor=8,
            total_floors=15,
            description="manual region seed 11110",
            latitude=Decimal("37.5759000"),
            longitude=Decimal("126.9735000"),
        ),
    ]


async def _cleanup_source_rows(session: AsyncSession) -> dict[str, int]:
    listing_ids = list(
        (await session.execute(select(Listing.id).where(Listing.source == SEED_SOURCE)))
        .scalars()
        .all()
    )

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

    listings_deleted = (
        await session.execute(
            select(func.count(Listing.id)).where(Listing.source == SEED_SOURCE)
        )
    ).scalar_one_or_none() or 0

    _ = await session.execute(delete(Listing).where(Listing.source == SEED_SOURCE))
    await session.commit()

    remaining_source_count = (
        await session.execute(
            select(func.count(Listing.id)).where(Listing.source == SEED_SOURCE)
        )
    ).scalar_one_or_none() or 0

    return {
        "seed_listing_ids_count": len(listing_ids),
        "favorites_deleted": int(favorites_deleted),
        "price_changes_deleted": int(price_changes_deleted),
        "listings_deleted": int(listings_deleted),
        "remaining_source_count": int(remaining_source_count),
    }


async def _count_seed_rows(session: AsyncSession) -> int:
    count = (
        await session.execute(
            select(func.count(Listing.id)).where(Listing.source == SEED_SOURCE)
        )
    ).scalar_one_or_none()
    return int(count or 0)


async def _clear_manual_check_cache() -> dict[str, object]:
    cleared_keys: list[dict[str, object]] = []

    for region_code in _CACHE_CLEAR_REGION_CODES:
        for limit in _CACHE_CLEAR_LIMITS:
            cache_key = build_search_cache_key(
                region_code=region_code,
                dong=None,
                property_type="apt",
                rent_type=None,
                min_deposit=None,
                max_deposit=None,
                min_monthly_rent=None,
                max_monthly_rent=None,
                min_area=None,
                max_area=None,
                min_floor=None,
                max_floor=None,
                source=None,
                limit=limit,
            )
            await cache_delete(cache_key)
            cleared_keys.append(
                {"region_code": region_code, "limit": limit, "cache_key": cache_key}
            )

    return {
        "cleared_key_count": len(cleared_keys),
        "keys": cleared_keys,
    }


async def _run(args: CliArgs) -> dict[str, object]:
    failures: list[str] = []
    cleanup: dict[str, int] | None = None
    cache_cleanup: dict[str, object] | None = None

    if args.cleanup_source_only:
        async with session_context() as session:
            cleanup = await _cleanup_source_rows(session)
        if cleanup["remaining_source_count"] != 0:
            failures.append("cleanup_remaining_source_count_nonzero")

    seed_rows = _build_seed_rows()
    async with session_context() as session:
        upsert_count = await upsert_listings(session, seed_rows)
    async with session_context() as session:
        observed_seed_row_count = await _count_seed_rows(session)

    if args.clear_cache:
        cache_cleanup = await _clear_manual_check_cache()

    if upsert_count <= 0:
        failures.append("upsert_count <= 0")
    if observed_seed_row_count < len(seed_rows):
        failures.append("observed_seed_row_count < expected_seed_rows")

    report: dict[str, object] = {
        "status": "success" if not failures else "failure",
        "executed_at": datetime.now(UTC).isoformat(),
        "seed_source": SEED_SOURCE,
        "cleanup_requested": args.cleanup_source_only,
        "cleanup": cleanup,
        "clear_cache_requested": args.clear_cache,
        "cache_cleanup": cache_cleanup,
        "expected_seed_rows": len(seed_rows),
        "upsert_count": upsert_count,
        "observed_seed_row_count": observed_seed_row_count,
        "seed_regions": [
            {"region_code": "41135", "dong": "성남시분당구", "property_type": "apt"},
            {"region_code": "11680", "dong": "강남구", "property_type": "apt"},
            {"region_code": "11680", "dong": "역삼동", "property_type": "apt"},
            {"region_code": "11110", "dong": "종로구", "property_type": "apt"},
        ],
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
