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


class ZigbangSchemaMismatchError(RuntimeError):
    pass


def _to_int(value: object | None, default: int = 0) -> int:
    if value is None:
        return default
    if isinstance(value, (int, float, Decimal)):
        return int(value)
    cleaned = str(value).replace(",", "").replace(" ", "")
    if cleaned == "":
        return default
    try:
        return int(cleaned)
    except ValueError:
        return default


def _to_decimal(value: object | None) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    cleaned = str(value).replace(",", "").replace(" ", "")
    if cleaned == "":
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _extract_source_id(item: dict[str, object]) -> str:
    for key in ("item_id", "itemId", "id"):
        raw = item.get(key)
        if raw is None:
            continue
        source_id = str(raw).strip()
        if source_id:
            return source_id
    return ""


def _has_listing_core_fields(item: dict[str, object]) -> bool:
    return (
        "deposit" in item
        and "rent" in item
        and ("address" in item or "full_address" in item)
    )


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
        self.last_run_metrics: dict[str, object] = {
            "raw_count": 0,
            "parsed_count": 0,
            "invalid_count": 0,
            "schema_keys_sample": [],
            "source_keys_sample": [],
        }

    ZIGBANG_PROPERTY_TYPE_CODES: dict[str, str] = {
        "아파트": "A1",
        "빌라/연립": "A2",
        "오피스텔": "A4",
    }
    PROPERTY_TYPE_CODES_MAP: dict[str, str] = {
        "A1": "apt",
        "A2": "villa",
        "A4": "officetel",
    }
    SALES_TYPE_CODES_MAP: dict[str, str] = {
        "G1": "jeonse",
        "G2": "monthly",
    }

    async def _search_by_region_name(
        self,
        client: httpx.AsyncClient,
        region_name: str,
        property_type: str,
        rent_type: str,
    ) -> list[dict[str, object]]:
        """Search listings by region name using Zigbang API."""

        property_type_code = self.ZIGBANG_PROPERTY_TYPE_CODES.get(property_type, "A1")
        rent_type_code = "G1" if rent_type == "전세" else "G2"

        search_url = f"{BASE_URL}/search?q={region_name}&typeCode={property_type_code}&salesTypeCode={rent_type_code}"

        try:
            response = await client.get(search_url, headers=self._headers)
            _ = response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                logger.warning(
                    "Search returned non-dict payload for region_name=%s",
                    region_name,
                )
                return []

            if payload.get("code") == "200":
                items = payload.get("items")
                if not isinstance(items, list):
                    return []
                normalized_items: list[dict[str, object]] = []
                for item in items:
                    if isinstance(item, dict):
                        normalized_items.append(
                            {str(key): value for key, value in item.items()}
                        )
                return normalized_items
            else:
                error_msg = f"Search failed for region_name={region_name}: {payload.get('message', 'Unknown error')}"
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
    ) -> dict[str, object] | None:
        """Fetch detailed item information using Zigbang API."""

        items_url = f"{BASE_URL}/items?item_ids={item_id}&detail=true"

        try:
            response = await client.get(items_url, headers=self._headers)
            _ = response.raise_for_status()
            payload = response.json()
            if isinstance(payload, dict):
                return {str(key): value for key, value in payload.items()}
            return None
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

    def _parse_item(
        self, item: dict[str, object], search_region: str
    ) -> ListingUpsert | None:
        """Parse Zigbang API item to ListingUpsert."""

        source_id = _extract_source_id(item)
        if not source_id:
            return None

        if not _has_listing_core_fields(item):
            return None

        property_type_raw = str(
            item.get("property_type_code") or item.get("property_type") or "A1"
        )
        sales_type_raw = str(
            item.get("sales_type_code") or item.get("sales_type") or "G1"
        )

        try:
            return ListingUpsert(
                source="zigbang",
                source_id=source_id,
                property_type=self.PROPERTY_TYPE_CODES_MAP.get(
                    property_type_raw,
                    PROPERTY_TYPE_MAP.get(property_type_raw, "apt"),
                ),
                rent_type=self.SALES_TYPE_CODES_MAP.get(
                    sales_type_raw,
                    TRADE_TYPE_MAP.get(sales_type_raw, "jeonse"),
                ),
                deposit=_to_int(item.get("deposit"), 0),
                monthly_rent=_to_int(item.get("rent"), 0),
                address=str(item.get("address", "")),
                dong=search_region,
                detail_address=(
                    str(item.get("full_address"))
                    if item.get("full_address") is not None
                    else None
                ),
                area_m2=_to_decimal(
                    item.get("exclusive_area_m2") or item.get("area_m2")
                ),
                floor=_to_int(item.get("floor1")),
                total_floors=None,
                description=str(item.get("comment", "")),
                latitude=None,
                longitude=None,
            )
        except (TypeError, ValueError, KeyError):
            return None

    async def run(self) -> CrawlResult[ListingUpsert]:
        """Fetch and parse Zigbang rental listings."""

        all_rows: list[ListingUpsert] = []
        errors: list[str] = []
        raw_item_count = 0
        parsed_count = 0
        invalid_count = 0
        schema_keys_sample: list[list[str]] = []
        source_keys_sample: list[list[str]] = []
        seen_schema_keys: set[tuple[str, ...]] = set()
        seen_source_keys: set[tuple[str, ...]] = set()

        if not self._region_names:
            logger.warning("No region_names configured - returning empty result")
            self.last_run_metrics = {
                "raw_count": 0,
                "parsed_count": 0,
                "invalid_count": 0,
                "schema_keys_sample": [],
                "source_keys_sample": [],
            }
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

                        raw_item_count += len(search_results)

                        for item in search_results:
                            top_level_keys = tuple(sorted(item.keys()))
                            if (
                                top_level_keys
                                and top_level_keys not in seen_schema_keys
                                and len(schema_keys_sample) < 3
                            ):
                                seen_schema_keys.add(top_level_keys)
                                schema_keys_sample.append(list(top_level_keys))

                            source_payload = item.get("_source")
                            if isinstance(source_payload, dict):
                                source_keys = tuple(
                                    sorted(str(key) for key in source_payload.keys())
                                )
                                if (
                                    source_keys
                                    and source_keys not in seen_source_keys
                                    and len(source_keys_sample) < 3
                                ):
                                    seen_source_keys.add(source_keys)
                                    source_keys_sample.append(list(source_keys))

                            row = self._parse_item(item, region_name)
                            if row:
                                all_rows.append(row)
                                parsed_count += 1
                            else:
                                invalid_count += 1

                        logger.info(
                            "Fetched %s items for region_name=%s, property_type=%s, rent_type=%s",
                            len(search_results),
                            region_name,
                            property_type,
                            rent_type,
                        )

                        if len(all_rows) % 20 == 0:
                            await asyncio.sleep(2.0)

        self.last_run_metrics = {
            "raw_count": raw_item_count,
            "parsed_count": parsed_count,
            "invalid_count": invalid_count,
            "schema_keys_sample": schema_keys_sample,
            "source_keys_sample": source_keys_sample,
        }

        if raw_item_count > 0 and parsed_count == 0:
            mismatch_message = f"Zigbang schema mismatch: raw items fetched but no valid listings parsed (raw_count={raw_item_count}, parsed_count={parsed_count}, invalid_count={invalid_count}, schema_keys_sample={schema_keys_sample}, source_keys_sample={source_keys_sample})"
            raise ZigbangSchemaMismatchError(mismatch_message)

        logger.info(f"Total fetched {len(all_rows)} listings with {len(errors)} errors")

        return CrawlResult(count=len(all_rows), rows=all_rows, errors=errors)
