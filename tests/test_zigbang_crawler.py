from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from src.crawlers.zigbang import ZigbangCrawler, ZigbangSchemaMismatchError

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
SEARCH_FIXTURE_PATH = FIXTURE_DIR / "zigbang_search_jongro_representative.json"
VALID_ITEM_FIXTURE_PATH = FIXTURE_DIR / "zigbang_listing_valid_item.json"
EXPECTED_REPRESENTATIVE_IDS = [
    8214,
    14060,
    2815,
    27544,
    12472,
    86875,
    79222,
    14794,
    59332,
    77125,
    9174,
    38010,
]
EXPECTED_REPRESENTATIVE_COUNT = 12
pytestmark = pytest.mark.anyio


@pytest.fixture
def zigbang_search_fixture() -> dict[str, Any]:
    return json.loads(SEARCH_FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def zigbang_search_items(
    zigbang_search_fixture: dict[str, Any],
) -> list[dict[str, Any]]:
    items = zigbang_search_fixture["items"]
    assert isinstance(items, list)
    return items


@pytest.fixture
def zigbang_valid_listing_item() -> dict[str, Any]:
    return json.loads(VALID_ITEM_FIXTURE_PATH.read_text(encoding="utf-8"))


async def test_zigbang_search_fixture_has_representative_items(
    zigbang_search_fixture: dict[str, Any],
    zigbang_search_items: list[dict[str, Any]],
) -> None:
    """Verify the fixture contains exactly the expected representative items."""
    metadata = zigbang_search_fixture["metadata"]

    # Check metadata structure
    assert isinstance(metadata, dict)
    assert "representative_item_count" in metadata
    assert "representative_item_ids" in metadata
    assert "observed_total_items_raw" in metadata
    assert "observed_unique_ids" in metadata

    # Verify item count and IDs against fixed contract
    assert metadata["representative_item_count"] == EXPECTED_REPRESENTATIVE_COUNT
    assert len(zigbang_search_items) == EXPECTED_REPRESENTATIVE_COUNT

    actual_ids = {item["id"] for item in zigbang_search_items}
    metadata_ids = set(metadata["representative_item_ids"])
    expected_ids = set(EXPECTED_REPRESENTATIVE_IDS)
    assert metadata_ids == expected_ids
    assert actual_ids == expected_ids

    # Observed counts are capture-time snapshots; verify only invariants.
    assert (
        metadata["observed_total_items_raw"]
        >= metadata["observed_unique_ids"]
        >= metadata["representative_item_count"]
    )


async def test_zigbang_search_fixture_schema_contract(
    zigbang_search_items: list[dict[str, Any]],
) -> None:
    """Verify all items have required keys and lack listing-specific fields."""
    required_keys = {"id", "type", "name", "_source"}

    for item in zigbang_search_items:
        assert required_keys.issubset(item.keys())
        assert "item_id" not in item
        assert "deposit" not in item
        assert "rent" not in item


async def test_zigbang_search_fixture_type_diversity(
    zigbang_search_items: list[dict[str, Any]],
) -> None:
    """Verify fixture contains both 'address' and 'apartment' types."""
    types = {item["type"] for item in zigbang_search_items}
    assert "address" in types
    assert "apartment" in types


async def test_parse_item_returns_none_for_search_payload(
    zigbang_search_items: list[dict[str, Any]],
) -> None:
    """Search payloads should not be parseable as listings."""
    crawler = ZigbangCrawler(region_names=["종로구"], property_types=["아파트"])
    parsed = crawler._parse_item(zigbang_search_items[0], "종로구")
    assert parsed is None


@pytest.mark.anyio
async def test_run_raises_schema_mismatch_when_all_items_invalid(
    monkeypatch: pytest.MonkeyPatch,
    zigbang_search_items: list[dict[str, Any]],
) -> None:
    """When all items fail parsing, raise ZigbangSchemaMismatchError with correct metrics."""
    crawler = ZigbangCrawler(region_names=["종로구"], property_types=["아파트"])
    search_call_count = 0

    async def fake_search_by_region_name(
        _client: Any,
        _region_name: str,
        _property_type: str,
        _rent_type: str,
    ) -> list[dict[str, Any]]:
        nonlocal search_call_count
        search_call_count += 1
        if search_call_count == 1:
            return zigbang_search_items
        return []

    async def fake_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(crawler, "_search_by_region_name", fake_search_by_region_name)
    monkeypatch.setattr("src.crawlers.zigbang.asyncio.sleep", fake_sleep)

    with pytest.raises(ZigbangSchemaMismatchError) as exc_info:
        await crawler.run()

    message = str(exc_info.value)
    raw_count = len(zigbang_search_items)

    # Verify error message contains expected metrics
    assert f"raw_count={raw_count}" in message
    assert "parsed_count=0" in message

    # Verify metrics were recorded correctly
    assert crawler.last_run_metrics["raw_count"] == raw_count
    assert crawler.last_run_metrics["parsed_count"] == 0
    assert crawler.last_run_metrics["invalid_count"] == raw_count


async def test_parse_item_maps_valid_listing_fixture(
    zigbang_valid_listing_item: dict[str, Any],
) -> None:
    """Valid listing payload should be parsed correctly."""
    crawler = ZigbangCrawler(region_names=["종로구"], property_types=["빌라/연립"])

    result = crawler._parse_item(zigbang_valid_listing_item, "종로구")

    assert result is not None
    assert result.source == "zigbang"
    assert result.source_id == "987654321"
    assert result.property_type == "villa"
    assert result.rent_type == "monthly"
    assert result.deposit == 25000
    assert result.monthly_rent == 80
    assert result.dong == "종로구"


async def test_search_retries_on_429_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    crawler = ZigbangCrawler(region_names=["종로구"], property_types=["아파트"])
    attempts = 0

    async def fake_sleep(_seconds: float) -> None:
        return None

    async def fake_get(
        _self: httpx.AsyncClient,
        url: str,
        **_kwargs: object,
    ) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        request = httpx.Request("GET", url)

        if attempts < 3:
            return httpx.Response(
                429,
                request=request,
                json={"code": "429", "message": "Too many requests"},
            )

        return httpx.Response(
            200,
            request=request,
            json={
                "code": "200",
                "items": [{"id": 123, "type": "apartment", "name": "sample"}],
            },
        )

    monkeypatch.setattr("src.crawlers.zigbang.asyncio.sleep", fake_sleep)
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    async with httpx.AsyncClient() as client:
        rows = await crawler._search_by_region_name(client, "종로구", "아파트", "전세")

    assert attempts == 3
    assert rows


async def test_search_stops_after_max_retries_on_429(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    crawler = ZigbangCrawler(region_names=["종로구"], property_types=["아파트"])

    async def fake_sleep(_seconds: float) -> None:
        return None

    async def fake_get(
        _self: httpx.AsyncClient,
        url: str,
        **_kwargs: object,
    ) -> httpx.Response:
        request = httpx.Request("GET", url)
        return httpx.Response(
            429,
            request=request,
            json={"code": "429", "message": "Too many requests"},
        )

    monkeypatch.setattr("src.crawlers.zigbang.asyncio.sleep", fake_sleep)
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    async with httpx.AsyncClient() as client:
        result = await crawler._search_by_region_name(
            client, "종로구", "아파트", "전세"
        )

    assert result == []
    retry_count = crawler.last_run_metrics["retry_count"]
    assert isinstance(retry_count, int)
    assert retry_count > 0
