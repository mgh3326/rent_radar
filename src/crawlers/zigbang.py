"""Zigbang rental crawler using region names and geohash filtering."""

import asyncio
import logging
from decimal import Decimal, InvalidOperation
from typing import Final

import httpx

from src.config import get_settings
from src.config.region_codes import region_codes_to_district_names
from src.crawlers.base import CrawlResult
from src.db.repositories import ListingUpsert

logger = logging.getLogger(__name__)
settings = get_settings()

TRADE_TYPE_MAP: Final = {"월세": "monthly", "전세": "jeonse"}
PROPERTY_TYPE_MAP: Final = {
    "아파트": "apt",
    "빌라/연립": "villa",
    "오피스텔": "officetel",
}
BASE_URL: Final = "https://apis.zigbang.com/v2"


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


class ZigbangCrawler:
    """Crawler for Zigbang rental listings using road map regions."""

    def __init__(
        self,
        region_names: list[str] | None = None,
        property_types: list[str] | None = None,
        radius_km: int = 5,
    ) -> None:
        self._region_names = region_names or region_codes_to_district_names(
            settings.target_region_codes
        )
        self._property_types = property_types or ["아파트", "빌라/연립", "오피스텔"]

        self._headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Referer": "https://zigbang.com/",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            "sec-ch-ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"macOS"',
        }

    ZIGBANG_PROPERTY_TYPE_CODES: dict[str, str] = {
        "아파트": "A1",
        "빌라/연립": "A2",
        "오피스텔": "A4",
    }

    async def _search_by_region_name(
        self,
        client: httpx.AsyncClient,
        region_name: str,
        property_type: str,
        rent_type: str,
    ) -> list[str]:
        """Search listings by region name using Zigbang API."""

        property_type_code = self.ZIGBANG_PROPERTY_TYPE_CODES.get(property_type, "A1")
        rent_type_code = "G1" if rent_type == "전세" else "G2"

        search_url = f"{BASE_URL}/search?q={region_name}&typeCode={property_type_code}&salesTypeCode={rent_type_code}"

        try:
            response = await client.get(search_url, headers=self._headers)
            response.raise_for_status()
            data = response.json()

            if data.get("code") == "200":
                return data.get("items", [])
            else:
                error_msg = f"Search failed for region_name={region_name}: {data.get('message', 'Unknown error')}"
                logger.warning(error_msg)
                return []

        except httpx.HTTPStatusError as e:
            error_msg = (
                f"HTTP {e.response.status_code} error for region_name={region_name}"
            )
            logger.warning(error_msg)
            return []
        except Exception as e:
            error_msg = f"Unexpected error for region_name={region_name}: {str(e)}"
            logger.warning(error_msg)
            return []

    async def _fetch_item_details(
        self,
        client: httpx.AsyncClient,
        item_id: str,
    ) -> dict | None:
        """Fetch detailed item information using Zigbang API."""

        items_url = f"{BASE_URL}/items?item_ids={item_id}&detail=true"

        try:
            response = await client.get(items_url, headers=self._headers)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            error_msg = (
                f"HTTP {e.response.status_code} error fetching item_id={item_id}"
            )
            logger.warning(error_msg)
            return None
        except Exception as e:
            error_msg = f"Unexpected error fetching item_id={item_id}: {str(e)}"
            logger.warning(error_msg)
            return None

    def _parse_item(self, item: dict, search_region: str) -> ListingUpsert | None:
        """Parse Zigbang API item to ListingUpsert."""

        try:
            return ListingUpsert(
                source="zigbang",
                source_id=str(item.get("item_id", "")),
                property_type=PROPERTY_TYPE_MAP.get(
                    item.get("property_type_code", "A1"), "apt"
                ),
                rent_type=TRADE_TYPE_MAP.get(
                    item.get("sales_type_code", "G1"), "jeonse"
                ),
                deposit=_to_int(item.get("deposit", ""), 0),
                monthly_rent=_to_int(item.get("rent", ""), 0),
                address=item.get("address", ""),
                dong=search_region,
                detail_address=item.get("full_address"),
                area_m2=_to_decimal(item.get("exclusive_area_m2")),
                floor=_to_int(item.get("floor1")),
                total_floors=None,
                description=item.get("comment", ""),
                latitude=None,
                longitude=None,
            )
        except (ValueError, KeyError):
            return None

    async def run(self) -> CrawlResult[ListingUpsert]:
        """Fetch and parse Zigbang rental listings."""

        all_rows: list[ListingUpsert] = []
        errors: list[str] = []

        if not self._region_names:
            logger.warning("No region_names configured - returning empty result")
            return CrawlResult(count=0, rows=[], errors=[])

        timeout = httpx.Timeout(settings.public_data_request_timeout_seconds)

        async with httpx.AsyncClient(timeout=timeout, headers=self._headers) as client:
            for region_name in self._region_names:
                for property_type in self._property_types:
                    for rent_type in ["전세", "월세"]:
                        await asyncio.sleep(1.0)

                        search_results = await self._search_by_region_name(
                            client, region_name, property_type, rent_type
                        )

                        if not search_results:
                            continue

                        for item in search_results:
                            row = self._parse_item(item, region_name)
                            if row:
                                all_rows.append(row)

                        logger.info(
                            f"Fetched {len(search_results)} items for "
                            f"region_name={region_name}, "
                            f"property_type={property_type}, "
                            f"rent_type={rent_type}"
                        )

                        if len(all_rows) % 20 == 0:
                            await asyncio.sleep(2.0)

        logger.info(f"Total fetched {len(all_rows)} listings with {len(errors)} errors")

        return CrawlResult(count=len(all_rows), rows=all_rows, errors=errors)
