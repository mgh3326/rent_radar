#!/usr/bin/env python
"""Regenerate the Zigbang representative fixture from live API data.

This script fetches data from the Zigbang API and extracts the 12 representative
items used for schema mismatch regression tests.

Usage:
    uv run python scripts/build_zigbang_representative_fixture.py

Exit codes:
    0: Success
    1: Failed to find all representative IDs
"""

from __future__ import annotations

import asyncio
from collections import Counter
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx

BASE_URL = "https://apis.zigbang.com/v2"
REGION_NAME = "종로구"
REQUEST_MATRIX = [
    ("아파트", "A1", "전세", "G1"),
    ("아파트", "A1", "월세", "G2"),
    ("빌라/연립", "A2", "전세", "G1"),
    ("빌라/연립", "A2", "월세", "G2"),
    ("오피스텔", "A4", "전세", "G1"),
    ("오피스텔", "A4", "월세", "G2"),
]
REPRESENTATIVE_IDS = [
    8214,  # address type
    14060,  # 평창동, 갑을
    2815,  # 무악동, 무악현대 (largest household: 964)
    27544,  # 동숭동, 동성
    12472,  # 창신동, 동대문 (oldest: 1966)
    86875,  # 숭인동, 에비뉴청계Ⅱ (newest: 2025)
    79222,  # 신문로2가, 디팰리스
    14794,  # 교북동, 동아
    59332,  # 당주동, 미도파
    77125,  # 통인동, 효자
    9174,  # 익선동, 현대뜨레비앙
    38010,  # 무악동, 경희궁롯데캐슬
]
OUT_PATH = Path("tests/fixtures/zigbang_search_jongro_representative.json")
EXPECTED_REPRESENTATIVE_COUNT = 12


def validate_representative_ids(
    representative_ids: list[int], expected_count: int
) -> None:
    """Fail fast if representative IDs are malformed."""
    if len(representative_ids) != expected_count:
        raise ValueError(
            f"REPRESENTATIVE_IDS length must be {expected_count}, got {len(representative_ids)}"
        )

    duplicate_ids = sorted(
        item_id for item_id, count in Counter(representative_ids).items() if count > 1
    )
    if duplicate_ids:
        raise ValueError(f"REPRESENTATIVE_IDS contains duplicates: {duplicate_ids}")


async def fetch_all_items() -> tuple[list[dict], list[dict]]:
    """Fetch all items from Zigbang API and return (items, request_matrix)."""
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://zigbang.com/",
        "Accept": "application/json, text/plain, */*",
    }
    items = []
    request_rows = []

    async with httpx.AsyncClient(timeout=20.0, headers=headers) as client:
        for property_type, type_code, rent_type, sales_code in REQUEST_MATRIX:
            url = (
                f"{BASE_URL}/search?q={REGION_NAME}"
                f"&typeCode={type_code}&salesTypeCode={sales_code}"
            )
            response = await client.get(url)
            response.raise_for_status()
            payload = response.json()
            batch = payload.get("items", [])
            items.extend(batch)
            request_rows.append(
                {
                    "region_name": REGION_NAME,
                    "property_type": property_type,
                    "type_code": type_code,
                    "rent_type": rent_type,
                    "sales_code": sales_code,
                    "count": len(batch),
                    "code": payload.get("code"),
                    "message": payload.get("message"),
                }
            )

    return items, request_rows


def extract_representative_items(
    all_items: list[dict],
    representative_ids: list[int],
) -> list[dict]:
    """Extract representative items by ID and preserve representative_ids order."""
    item_by_id: dict[int, dict] = {}

    for item in all_items:
        item_id = item.get("id")
        if not isinstance(item_id, int):
            continue
        if item_id in representative_ids and item_id not in item_by_id:
            item_by_id[item_id] = item

    return [item_by_id[item_id] for item_id in representative_ids if item_id in item_by_id]


async def main() -> int:
    try:
        validate_representative_ids(REPRESENTATIVE_IDS, EXPECTED_REPRESENTATIVE_COUNT)
    except ValueError as exc:
        print(f"ERROR: {exc}")
        return 1

    print(f"Fetching items from Zigbang API for {REGION_NAME}...")
    all_items, request_matrix = await fetch_all_items()

    unique_ids = {item["id"] for item in all_items}
    print(f"Total items: {len(all_items)}, unique IDs: {len(unique_ids)}")

    print(f"Extracting {len(REPRESENTATIVE_IDS)} representative items...")
    rep_items = extract_representative_items(all_items, REPRESENTATIVE_IDS)

    found_ids = {item["id"] for item in rep_items}
    missing_ids = set(REPRESENTATIVE_IDS) - found_ids

    if missing_ids:
        print(f"ERROR: Missing representative IDs: {sorted(missing_ids)}")
        return 1

    if len(rep_items) != len(REPRESENTATIVE_IDS):
        print(
            "ERROR: Representative item count mismatch "
            f"(expected={len(REPRESENTATIVE_IDS)}, actual={len(rep_items)})"
        )
        return 1

    fixture = {
        "metadata": {
            "captured_at": datetime.now(UTC).isoformat(),
            "region_name": REGION_NAME,
            "request_matrix": request_matrix,
            "observed_total_items_raw": len(all_items),
            "observed_unique_ids": len(unique_ids),
            "representative_item_ids": REPRESENTATIVE_IDS,
            "representative_item_count": len(REPRESENTATIVE_IDS),
        },
        "items": rep_items,
    }

    OUT_PATH.write_text(
        json.dumps(fixture, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Wrote {OUT_PATH} with {len(rep_items)} items")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
