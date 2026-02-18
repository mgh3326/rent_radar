from __future__ import annotations

from typing import Any

import httpx
import pytest

from src.crawlers.naver import NaverCrawler

pytestmark = pytest.mark.anyio


@pytest.fixture
def naver_article_json() -> list[dict[str, Any]]:
    return [
        {
            "articleNo": "123456",
            "realEstateTypeName": "아파트",
            "tradeTypeName": "월세",
            "dealOrWarrantPrc": "5000",
            "rentPrc": "50",
            "articleFeatureDesc": "테스트 매물",
            "latitude": "37.572",
            "longitude": "126.979",
        }
    ]


@pytest.fixture
def legacy_naver_article_json() -> dict[str, Any]:
    return {
        "articleNo": "654321",
        "realEstateType": "APT",
        "tradeType": "B1",
        "price1": "50,000",
        "price2": "0",
        "address": "서울특별시 종로구 사직동 123-45",
        "dong": "사직동",
        "detailAddress": "101동 101호",
        "area1": "59.99",
        "floorInfo": "9/15",
        "description": "레거시 필드 테스트",
        "lat": "37.564",
        "lng": "126.989",
    }


async def test_naver_crawler_parse_article(
    naver_article_json: list[dict[str, Any]],
) -> None:
    crawler = NaverCrawler(region_codes=["11110"], property_types=["APT"])
    row = crawler._parse_article(naver_article_json[0], "11110")

    assert row is not None
    assert row.source == "naver"
    assert row.source_id == "123456"


async def test_naver_crawler_parse_article_supports_legacy_fields(
    legacy_naver_article_json: dict[str, Any],
) -> None:
    crawler = NaverCrawler(region_codes=["11110"], property_types=["APT"])
    row = crawler._parse_article(legacy_naver_article_json, "11110")

    assert row is not None
    assert row.source == "naver"
    assert row.source_id == "654321"
    assert row.property_type == "apt"
    assert row.rent_type == "jeonse"
    assert row.deposit == 50000
    assert row.monthly_rent == 0
    assert row.dong == "사직동"
    assert row.latitude is not None
    assert row.longitude is not None
    assert float(row.latitude) == pytest.approx(37.564)
    assert float(row.longitude) == pytest.approx(126.989)
    assert row.floor == 9
    assert row.total_floors == 15


async def test_naver_crawler_parse_article_floor_b1_is_not_positive(
    legacy_naver_article_json: dict[str, Any],
) -> None:
    crawler = NaverCrawler(region_codes=["11110"], property_types=["APT"])
    article = {**legacy_naver_article_json, "floorInfo": "B1/20"}

    row = crawler._parse_article(article, "11110")

    assert row is not None
    assert row.floor == -1
    assert row.total_floors == 20


async def test_request_articles_uses_retry_after_header_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    crawler = NaverCrawler(region_codes=["11110"], property_types=["APT"])
    attempts = 0
    sleep_calls: list[float] = []

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
                headers={"Retry-After": "7"},
                json={"error": "too many requests"},
            )
        return httpx.Response(
            200,
            request=request,
            json={"articleList": [{"articleNo": "123456"}]},
        )

    monkeypatch.setattr("src.crawlers.naver.asyncio.sleep", fake_sleep)
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    result = await crawler._request_articles(
        region_code="11110",
        property_type="APT",
        trade_type="B2",
    )

    assert attempts == 2
    assert len(result) == 1
    assert sleep_calls == [7.0]


async def test_request_articles_falls_back_to_exponential_backoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    crawler = NaverCrawler(region_codes=["11110"], property_types=["APT"])
    attempts = 0
    sleep_calls: list[float] = []

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
        if attempts < 3:
            return httpx.Response(
                429,
                request=request,
                json={"error": "too many requests"},
            )
        return httpx.Response(
            200,
            request=request,
            json={"articleList": [{"articleNo": "123456"}]},
        )

    monkeypatch.setattr("src.crawlers.naver.asyncio.sleep", fake_sleep)
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    monkeypatch.setattr(crawler, "_apply_jitter", lambda base: base, raising=False)

    result = await crawler._request_articles(
        region_code="11110",
        property_type="APT",
        trade_type="B2",
    )

    assert attempts == 3
    assert len(result) == 1
    assert sleep_calls == [1.0, 2.0]


async def test_run_applies_base_throttle_before_each_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    crawler = NaverCrawler(
        region_codes=["11110"],
        property_types=["APT"],
        base_delay_seconds=1.5,
    )
    sleep_calls: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    async def fake_request_articles(
        *,
        client: httpx.AsyncClient,
        region_code: str,
        property_type: str,
        trade_type: str,
    ) -> list[dict[str, Any]]:
        _ = client
        _ = region_code
        _ = property_type
        _ = trade_type
        return []

    monkeypatch.setattr("src.crawlers.naver.asyncio.sleep", fake_sleep)
    monkeypatch.setattr(
        crawler, "_request_articles_with_client", fake_request_articles
    )

    result = await crawler.run()

    assert result.count == 0
    assert result.errors == []
    assert sleep_calls == [1.5, 1.5]


async def test_run_returns_error_context_when_429_retry_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    crawler = NaverCrawler(
        region_codes=["11110"],
        property_types=["APT"],
        max_retries=1,
    )
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
            429,
            request=request,
            json={"error": "too many requests"},
        )

    monkeypatch.setattr("src.crawlers.naver.asyncio.sleep", fake_sleep)
    monkeypatch.setattr(crawler, "_apply_jitter", lambda base: base, raising=False)
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    result = await crawler.run()

    assert attempts == 2
    assert result.count == 0
    assert result.errors
    assert (
        "HTTP 429 exhausted retries for region_code=11110, property_type=APT, trade_type=B1"
        in result.errors[0]
    )
