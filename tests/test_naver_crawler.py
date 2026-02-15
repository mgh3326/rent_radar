"""Tests for Naver crawler using JSON fixtures."""

from decimal import Decimal

import pytest

from src.crawlers.naver import NaverCrawler


@pytest.fixture
def naver_article_json() -> list[dict]:
    """Sample Naver API article response."""
    return [
        {
            "articleNo": "123456",
            "realEstateType": "APT",
            "tradeType": "B1",
            "price1": "50,000",
            "price2": "",
            "address": "서울특별시 종로구 사직동 123-45",
            "dong": "사직동",
            "detailAddress": "101동 101호",
            "area1": "59.99",
            "floorInfo": "9/15",
            "description": "테스트 매물입니다.",
            "lat": "37.564",
            "lng": "126.989",
        }
    ]


@pytest.mark.anyio
async def test_naver_crawler_parse_article(naver_article_json: list[dict]) -> None:
    """NaverCrawler correctly parses article JSON to ListingUpsert."""

    crawler = NaverCrawler(region_codes=["11110"], property_types=["APT"])

    for article in naver_article_json:
        result = crawler._parse_article(article, "11110")

        assert result is not None
        assert result.source == "naver"
        assert result.source_id == "123456"
        assert result.property_type == "apt"
        assert result.rent_type == "jeonse"
        assert result.deposit == 50000
        assert result.monthly_rent == 0
        assert result.address == "서울특별시 종로구 사직동 123-45"
        assert result.dong == "사직동"
        assert result.area_m2 == Decimal("59.99")
        assert result.floor == 9
        assert result.total_floors == 15


@pytest.mark.anyio
async def test_naver_crawler_parse_article_monthly_rent(
    naver_article_json: list[dict],
) -> None:
    """NaverCrawler correctly parses monthly rent articles."""

    monthly_rent_article = {
        **naver_article_json[0],
        "tradeType": "B2",
        "price2": "50",
    }

    crawler = NaverCrawler(region_codes=["11110"], property_types=["APT"])
    result = crawler._parse_article(monthly_rent_article, "11110")

    assert result is not None
    assert result.rent_type == "monthly"
    assert result.monthly_rent == 50


@pytest.mark.anyio
async def test_naver_crawler_invalid_article() -> None:
    """NaverCrawler returns None for invalid article data."""

    crawler = NaverCrawler(region_codes=["11110"], property_types=["APT"])

    invalid_article = {"articleNo": ""}

    result = crawler._parse_article(invalid_article, "11110")

    assert result is None
