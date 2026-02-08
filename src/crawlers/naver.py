"""Naver Real Estate API crawler."""

import asyncio
import logging
from decimal import Decimal, InvalidOperation
from typing import Final

import httpx

from src.config import get_settings
from src.crawlers.base import CrawlResult
from src.db.repositories import ListingUpsert

logger = logging.getLogger(__name__)
settings = get_settings()

TRADE_TYPE_MAP: Final = {"B1": "jeonse", "B2": "monthly"}
PROPERTY_TYPE_MAP: Final = {
    "APT": "apt",
    "VILLA": "villa",
    "OPST": "officetel",
    "ONEROOM": "oneroom",
}
BASE_URL: Final = "https://new.land.naver.com/api"


def _to_int(value: str | None, default: int = 0) -> int:
    if not value:
        return default
    cleaned = value.replace(",", "").replace(" ", "")
    if cleaned == "":
        return default
    try:
        return int(cleaned)
    except ValueError:
        return default


def _to_decimal(value: str | None) -> Decimal | None:
    if not value:
        return None
    cleaned = value.replace(",", "").replace(" ", "")
    if cleaned == "":
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _parse_floor(floor_info: str | None) -> int | None:
    if not floor_info:
        return None
    parts = floor_info.split("/")
    if len(parts) == 2:
        try:
            return int(parts[0].strip())
        except ValueError:
            return None
    return None


def _parse_total_floors(floor_info: str | None) -> int | None:
    if not floor_info:
        return None
    parts = floor_info.split("/")
    if len(parts) == 2:
        try:
            return int(parts[1].strip())
        except ValueError:
            return None
    return None


class NaverCrawler:
    """Crawler for Naver Real Estate API."""

    def __init__(
        self,
        region_codes: list[str] | None = None,
        property_types: list[str] | None = None,
    ) -> None:
        self._region_codes = region_codes or settings.target_region_codes
        self._property_types = property_types or ["APT", "VILLA", "OPST", "ONEROOM"]

        self._headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Referer": "https://new.land.naver.com/articles",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            "sec-ch-ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"macOS"',
        }

    async def _request_articles(
        self,
        client: httpx.AsyncClient,
        region_code: str,
        property_type: str,
        trade_type: str,
        max_retries: int = 3,
    ) -> list[dict]:
        """Request articles from Naver API with retry logic for 429."""

        for attempt in range(max_retries):
            try:
                response = await client.get(
                    f"{BASE_URL}/articles",
                    params={
                        "cortarNo": region_code,
                        "realEstateType": property_type,
                        "tradeType": trade_type,
                    },
                    headers=self._headers,
                )
                response.raise_for_status()
                data = response.json()

                if not data.get("success", False):
                    return []

                return data.get("articleList", [])

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    if attempt < max_retries - 1:
                        backoff = 2**attempt
                        logger.warning(
                            f"Rate limit exceeded (attempt {attempt + 1}/{max_retries}) for "
                            f"region_code={region_code}, property_type={property_type}, "
                            f"trade_type={trade_type}. Retrying after {backoff}s..."
                        )
                        await asyncio.sleep(backoff)
                    else:
                        logger.warning(
                            f"Rate limit exceeded after {max_retries} attempts for "
                            f"region_code={region_code}, property_type={property_type}, "
                            f"trade_type={trade_type}. Giving up."
                        )
                else:
                    raise

        return []

    def _parse_article(self, article: dict, region_code: str) -> ListingUpsert | None:
        """Parse single article to ListingUpsert."""

        try:
            return ListingUpsert(
                source="naver",
                source_id=str(article.get("articleNo", "")),
                property_type=PROPERTY_TYPE_MAP.get(
                    article.get("realEstateType", "APT"), "apt"
                ),
                rent_type=TRADE_TYPE_MAP.get(article.get("tradeType", "B1"), "jeonse"),
                deposit=_to_int(article.get("price1"), 0),
                monthly_rent=_to_int(article.get("price2"), 0),
                address=article.get("address", ""),
                dong=article.get("dong"),
                detail_address=article.get("detailAddress"),
                area_m2=_to_decimal(article.get("area1")),
                floor=_parse_floor(article.get("floorInfo")),
                total_floors=_parse_total_floors(article.get("floorInfo")),
                description=article.get("description", ""),
                latitude=_to_decimal(article.get("lat")),
                longitude=_to_decimal(article.get("lng")),
            )
        except (ValueError, KeyError):
            return None

    async def run(self) -> CrawlResult[ListingUpsert]:
        """Fetch and parse Naver Real Estate listings."""

        all_rows: list[ListingUpsert] = []
        errors: list[str] = []
        timeout = httpx.Timeout(settings.public_data_request_timeout_seconds)

        async with httpx.AsyncClient(timeout=timeout, headers=self._headers) as client:
            for region_code in self._region_codes:
                for property_type in self._property_types:
                    for trade_type in ["B1", "B2"]:
                        try:
                            await asyncio.sleep(1.5)

                            articles = await self._request_articles(
                                client, region_code, property_type, trade_type
                            )

                            for article in articles:
                                row = self._parse_article(article, region_code)
                                if row:
                                    all_rows.append(row)

                            logger.info(
                                f"Fetched {len(articles)} articles for "
                                f"region_code={region_code}, "
                                f"property_type={property_type}, "
                                f"trade_type={trade_type}"
                            )

                        except httpx.HTTPStatusError as e:
                            error_msg = (
                                f"HTTP {e.response.status_code} error for "
                                f"region_code={region_code}, "
                                f"property_type={property_type}, "
                                f"trade_type={trade_type}"
                            )
                            logger.warning(error_msg)
                            errors.append(error_msg)
                        except Exception as e:
                            error_msg = (
                                f"Unexpected error for "
                                f"region_code={region_code}, "
                                f"property_type={property_type}, "
                                f"trade_type={trade_type}: {str(e)}"
                            )
                            logger.warning(error_msg)
                            errors.append(error_msg)

        logger.info(f"Total fetched {len(all_rows)} listings with {len(errors)} errors")

        return CrawlResult(count=len(all_rows), rows=all_rows, errors=errors)
