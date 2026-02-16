from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

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
async def test_run_parses_apartment_catalog_items(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    crawler = ZigbangCrawler(
        region_names=["성남시분당구"],
        region_codes=["41135"],
        property_types=["아파트"],
    )
    apt_catalog_item = {
        "areaHoId": 13099125,
        "tranType": "rental",
        "local1": "경기도",
        "areaDanjiName": "산운마을13단지태영데시앙",
        "local2": "성남시 분당구",
        "local3": "운중동",
        "depositMin": 50000,
        "rentMin": 120,
        "sizeM2": 84.92,
        "dong": "1306동",
        "itemTitle": "테스트 아파트 매물",
        "itemIdList": [{"itemSource": "zigbang", "itemId": 47992593}],
    }

    async def fake_fetch_apt_item_catalogs(
        _client: Any,
        region_code: str | None,
    ) -> list[dict[str, Any]]:
        assert region_code == "41135"
        return [apt_catalog_item]

    async def fake_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(
        crawler,
        "_fetch_apt_item_catalogs",
        fake_fetch_apt_item_catalogs,
        raising=False,
    )
    monkeypatch.setattr("src.crawlers.zigbang.asyncio.sleep", fake_sleep)

    result = await crawler.run()

    assert result.count == 1
    assert len(result.rows) == 1
    row = result.rows[0]
    assert row.source_id == "47992593"
    assert row.property_type == "apt"
    assert row.rent_type == "monthly"
    assert row.deposit == 50000
    assert row.monthly_rent == 120
    assert row.address == "경기도 성남시 분당구 운중동"
    assert row.dong == "운중동"
    assert crawler.last_run_metrics["raw_count"] == 1
    assert crawler.last_run_metrics["parsed_count"] == 1
    assert crawler.last_run_metrics["invalid_count"] == 0

@pytest.mark.anyio
async def test_fetch_apt_item_catalogs_propagates_payload_local1(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    crawler = ZigbangCrawler(region_names=["성남시분당구"], property_types=["아파트"])
    call_count = 0

    async def fake_request_json_with_retry(
        _client: Any,
        _url: str,
        params: dict[str, object] | None = None,
    ) -> dict[str, Any] | None:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            assert params is not None
            assert params.get("offset") == "0"
            return {
                "local1": "경기도",
                "count": 1,
                "list": [
                    {
                        "local2": "성남시 분당구",
                        "local3": "정자동",
                        "tranType": "charter",
                        "depositMin": 55000,
                        "rentMin": 0,
                        "itemIdList": [{"itemId": 47981174}],
                    }
                ],
            }
        return {"local1": "경기도", "count": 1, "list": []}

    monkeypatch.setattr(crawler, "_request_json_with_retry", fake_request_json_with_retry)

    items = await crawler._fetch_apt_item_catalogs(cast(Any, object()), "41135")

    assert len(items) == 1
    assert items[0]["local1"] == "경기도"
    assert call_count == 1


@pytest.mark.anyio
async def test_run_fetches_detail_payload_when_search_item_is_not_listing(
    monkeypatch: pytest.MonkeyPatch,
    zigbang_search_items: list[dict[str, Any]],
    zigbang_valid_listing_item: dict[str, Any],
) -> None:
    """When search returns summary items, crawler should fetch details before parsing."""
    crawler = ZigbangCrawler(region_names=["종로구"], property_types=["아파트"])
    search_call_count = 0
    detail_calls: list[str] = []
    search_item = zigbang_search_items[1]
    expected_item_id = str(search_item["id"])

    async def fake_search_by_region_name(
        _client: Any,
        _region_name: str,
        _property_type: str,
        _rent_type: str,
    ) -> list[dict[str, Any]]:
        nonlocal search_call_count
        search_call_count += 1
        if search_call_count == 1:
            return [search_item]
        return []

    async def fake_fetch_item_details(
        _client: Any,
        item_id: str,
    ) -> dict[str, Any]:
        detail_calls.append(item_id)
        return {"items": [zigbang_valid_listing_item]}

    async def fake_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(crawler, "_search_by_region_name", fake_search_by_region_name)
    monkeypatch.setattr(crawler, "_fetch_item_details", fake_fetch_item_details)
    monkeypatch.setattr("src.crawlers.zigbang.asyncio.sleep", fake_sleep)

    result = await crawler.run()

    assert result.count == 1
    assert len(result.rows) == 1
    assert result.rows[0].source_id == "987654321"
    assert detail_calls == [expected_item_id]
    assert crawler.last_run_metrics["raw_count"] == 1
    assert crawler.last_run_metrics["parsed_count"] == 1
    assert crawler.last_run_metrics["invalid_count"] == 0


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

    async def fake_fetch_item_details(
        _client: Any,
        _item_id: str,
    ) -> dict[str, Any] | None:
        return None

    monkeypatch.setattr(crawler, "_search_by_region_name", fake_search_by_region_name)
    monkeypatch.setattr(crawler, "_fetch_item_details", fake_fetch_item_details)
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


async def test_search_retries_on_500_then_succeeds(
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
        if attempts == 1:
            return httpx.Response(
                500,
                request=request,
                json={"code": "500", "message": "Internal server error"},
            )

        return httpx.Response(
            200,
            request=request,
            json={
                "code": "200",
                "items": [{"id": 1234, "type": "apartment", "name": "sample"}],
            },
        )

    monkeypatch.setattr("src.crawlers.zigbang.asyncio.sleep", fake_sleep)
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    async with httpx.AsyncClient() as client:
        rows = await crawler._search_by_region_name(client, "종로구", "아파트", "전세")

    assert attempts == 2
    assert rows


async def test_search_does_not_retry_on_404(
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
        return httpx.Response(
            404,
            request=request,
            json={"code": "404", "message": "Not found"},
        )

    monkeypatch.setattr("src.crawlers.zigbang.asyncio.sleep", fake_sleep)
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    async with httpx.AsyncClient() as client:
        rows = await crawler._search_by_region_name(client, "종로구", "아파트", "전세")

    assert attempts == 1
    assert rows == []


async def test_retry_backoff_applies_jitter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    crawler = ZigbangCrawler(
        region_names=["종로구"],
        property_types=["아파트"],
        max_retries=1,
        base_delay_seconds=1.0,
        max_backoff_seconds=12.0,
    )
    sleep_calls: list[float] = []
    attempts = 0

    async def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    async def fake_get(
        _self: httpx.AsyncClient,
        url: str,
        **_kwargs: object,
    ) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        request = httpx.Request("GET", url)
        if attempts == 1:
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
                "items": [{"id": 1, "type": "apartment", "name": "sample"}],
            },
        )

    monkeypatch.setattr("src.crawlers.zigbang.asyncio.sleep", fake_sleep)
    monkeypatch.setattr("random.uniform", lambda _low, _high: 0.1)
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    async with httpx.AsyncClient() as client:
        rows = await crawler._search_by_region_name(client, "종로구", "아파트", "전세")

    assert rows
    assert attempts == 2
    assert sleep_calls == [1.1]


async def test_run_uses_configured_base_delay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    crawler = ZigbangCrawler(
        region_names=["종로구"],
        property_types=["아파트"],
        base_delay_seconds=1.5,
    )
    sleep_calls: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    async def fake_search_by_region_name(
        _client: httpx.AsyncClient,
        _region_name: str,
        _property_type: str,
        _rent_type: str,
    ) -> list[dict[str, object]]:
        return []

    monkeypatch.setattr("src.crawlers.zigbang.asyncio.sleep", fake_sleep)
    monkeypatch.setattr(crawler, "_search_by_region_name", fake_search_by_region_name)

    result = await crawler.run()

    assert result.count == 0
    assert sleep_calls[:2] == [1.5, 1.5]
