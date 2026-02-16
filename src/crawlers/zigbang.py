"""Zigbang rental crawler using region names and geohash filtering."""

import asyncio
import logging
import random
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
APT_BASE_URL: Final = "https://apis.zigbang.com/apt/locals"
DEFAULT_MAX_RETRIES: Final = 4
DEFAULT_BASE_DELAY_SECONDS: Final = 1.0
DEFAULT_MAX_BACKOFF_SECONDS: Final = 12.0
DEFAULT_COOLDOWN_SECONDS: Final = 20.0
DEFAULT_COOLDOWN_THRESHOLD: Final = 3
DEFAULT_JITTER_RATIO: Final = 0.2
RETRYABLE_HTTP_STATUS_CODES: Final = frozenset({429, 500, 502, 503, 504})
APT_TRAN_TYPE_MAP: Final = {
    "charter": "jeonse",
    "rental": "monthly",
}


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


def _to_optional_int(value: object | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float, Decimal)):
        return int(value)

    cleaned = str(value).replace(",", "").replace(" ", "")
    if cleaned == "":
        return None

    if cleaned.startswith("-"):
        if cleaned[1:].isdigit():
            return int(cleaned)
        return None

    if cleaned.isdigit():
        return int(cleaned)

    return None


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


def _extract_apt_catalog_source_id(item: dict[str, object]) -> str:
    item_id_list = item.get("itemIdList")
    if isinstance(item_id_list, list):
        for item_entry in item_id_list:
            if not isinstance(item_entry, dict):
                continue
            raw_item_id = item_entry.get("itemId")
            if raw_item_id is None:
                continue
            source_id = str(raw_item_id).strip()
            if source_id:
                return source_id

    raw_area_ho_id = item.get("areaHoId")
    if raw_area_ho_id is not None:
        fallback_source_id = str(raw_area_ho_id).strip()
        if fallback_source_id:
            return fallback_source_id

    return ""


def _has_listing_core_fields(item: dict[str, object]) -> bool:
    return (
        "deposit" in item
        and "rent" in item
        and ("address" in item or "full_address" in item)
    )


def _normalize_item_dict(value: dict[object, object]) -> dict[str, object]:
    return {str(key): item for key, item in value.items()}


def _extract_detail_listing_candidates(
    payload: dict[str, object],
) -> list[dict[str, object]]:
    candidates: list[dict[str, object]] = []

    def append_dict(value: object) -> None:
        if isinstance(value, dict):
            candidates.append(_normalize_item_dict(value))

    root_items = payload.get("items")
    if isinstance(root_items, list):
        for item in root_items:
            append_dict(item)

    append_dict(payload.get("item"))

    root_data = payload.get("data")
    if isinstance(root_data, dict):
        normalized_data = _normalize_item_dict(root_data)
        data_items = normalized_data.get("items")
        if isinstance(data_items, list):
            for item in data_items:
                append_dict(item)
        append_dict(normalized_data.get("item"))
        if _has_listing_core_fields(normalized_data):
            candidates.append(normalized_data)

    if _has_listing_core_fields(payload):
        candidates.append(payload)

    return candidates


class ZigbangCrawler:
    """Crawler for Zigbang rental listings using road map regions."""

    def __init__(
        self,
        region_names: list[str] | None = None,
        region_codes: list[str] | None = None,
        property_types: list[str] | None = None,
        radius_km: int = 5,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_delay_seconds: float = DEFAULT_BASE_DELAY_SECONDS,
        max_backoff_seconds: float = DEFAULT_MAX_BACKOFF_SECONDS,
        cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS,
        cooldown_threshold: int = DEFAULT_COOLDOWN_THRESHOLD,
    ) -> None:
        self._region_names = region_names or region_codes_to_district_names(
            settings.target_region_codes
        )
        self._region_codes = (
            [str(code) for code in region_codes] if region_codes is not None else None
        )
        self._property_types = property_types or ["아파트", "빌라/연립", "오피스텔"]
        self._max_retries = max(0, max_retries)
        self._base_delay_seconds = max(0.0, base_delay_seconds)
        self._max_backoff_seconds = max(self._base_delay_seconds, max_backoff_seconds)
        self._cooldown_seconds = max(0.0, cooldown_seconds)
        self._cooldown_threshold = max(1, cooldown_threshold)
        self._jitter_ratio = max(0.0, DEFAULT_JITTER_RATIO)
        self._retry_count = 0
        self._cooldown_count = 0

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
            "retry_count": 0,
            "cooldown_count": 0,
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

        payload = await self._request_json_with_retry(client, search_url)
        if not payload:
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

        error_msg = f"Search failed for region_name={region_name}: {payload.get('message', 'Unknown error')}"
        logger.warning(error_msg)
        return []

    async def _fetch_apt_item_catalogs(
        self,
        client: httpx.AsyncClient,
        region_code: str | None,
    ) -> list[dict[str, object]]:
        if not region_code:
            return []

        apt_url = f"{APT_BASE_URL}/{region_code}/item-catalogs"
        page_size = 20
        offset = 0
        normalized_items: list[dict[str, object]] = []

        while True:
            payload = await self._request_json_with_retry(
                client,
                apt_url,
                params={
                    "tranTypeIn[0]": "trade",
                    "tranTypeIn[1]": "charter",
                    "tranTypeIn[2]": "rental",
                    "includeOfferItem": "true",
                    "offset": str(offset),
                    "limit": str(page_size),
                },
            )
            if not payload:
                break

            raw_items = payload.get("list")
            if not isinstance(raw_items, list) or not raw_items:
                break
            local1 = payload.get("local1")
            local1_value = str(local1).strip() if local1 is not None else ""
            for item in raw_items:
                if isinstance(item, dict):
                    normalized_item = {str(key): value for key, value in item.items()}
                    if local1_value and "local1" not in normalized_item:
                        normalized_item["local1"] = local1_value
                    normalized_items.append(normalized_item)
            total_count = _to_int(payload.get("count"), 0)
            offset += page_size

            if len(raw_items) < page_size:
                break
            if total_count > 0 and offset >= total_count:
                break

        return normalized_items

    async def _request_json_with_retry(
        self,
        client: httpx.AsyncClient,
        url: str,
        params: dict[str, object] | None = None,
    ) -> dict[str, object] | None:
        consecutive_429 = 0
        total_attempts = self._max_retries + 1

        for attempt in range(total_attempts):
            try:
                response = await client.get(url, headers=self._headers, params=params)
                _ = response.raise_for_status()
                payload = response.json()
                if isinstance(payload, dict):
                    return {str(key): value for key, value in payload.items()}
                logger.warning("Request returned non-dict payload for url=%s", url)
                return None

            except httpx.HTTPStatusError as e:
                status_code = e.response.status_code
                if status_code not in RETRYABLE_HTTP_STATUS_CODES:
                    logger.warning("HTTP %s error for url=%s", status_code, url)
                    return None

                self._retry_count += 1
                self.last_run_metrics["retry_count"] = self._retry_count

                if attempt >= self._max_retries:
                    logger.warning(
                        "HTTP %s retry exhausted for url=%s",
                        status_code,
                        url,
                    )
                    return None

                if status_code == 429:
                    consecutive_429 += 1
                else:
                    consecutive_429 = 0

                backoff_seconds = min(
                    self._base_delay_seconds * (2**attempt),
                    self._max_backoff_seconds,
                )

                if consecutive_429 >= self._cooldown_threshold:
                    self._cooldown_count += 1
                    self.last_run_metrics["cooldown_count"] = self._cooldown_count
                    await asyncio.sleep(self._cooldown_seconds)
                    consecutive_429 = 0

                await asyncio.sleep(self._apply_jitter(backoff_seconds))

            except Exception as e:
                error_msg = f"Unexpected error for url={url}: {str(e)}"
                logger.warning(error_msg)
                return None

        return None

    def _apply_jitter(self, base_seconds: float) -> float:
        if base_seconds <= 0:
            return 0.0
        ratio = random.uniform(-self._jitter_ratio, self._jitter_ratio)
        jittered = base_seconds * (1 + ratio)
        return max(0.0, jittered)

    async def _fetch_item_details(
        self,
        client: httpx.AsyncClient,
        item_id: str,
    ) -> dict[str, object] | None:
        """Fetch detailed item information using Zigbang API."""

        # v3 item endpoint is currently used by active Zigbang listing detail flows.
        item_url = f"https://apis.zigbang.com/v3/items/{item_id}"
        payload = await self._request_json_with_retry(client, item_url)
        if payload is not None:
            return payload

        # Keep legacy fallback for compatibility with older fixtures/contracts.
        legacy_item_url = f"{BASE_URL}/items?item_ids={item_id}&detail=true"
        fallback_payload = await self._request_json_with_retry(client, legacy_item_url)
        if fallback_payload is None:
            logger.warning("Failed to fetch item details for item_id=%s", item_id)
        return fallback_payload

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

    def _parse_apt_catalog_item(
        self, item: dict[str, object], search_region: str
    ) -> ListingUpsert | None:
        source_id = _extract_apt_catalog_source_id(item)
        if not source_id:
            return None

        tran_type = str(item.get("tranType", "")).strip().lower()
        rent_type = APT_TRAN_TYPE_MAP.get(tran_type)
        if rent_type is None:
            return None

        local1 = str(item.get("local1", "")).strip()
        local2 = str(item.get("local2", "")).strip()
        local3 = str(item.get("local3", "")).strip()
        address = (
            " ".join(part for part in (local1, local2, local3) if part) or search_region
        )
        dong = local3 or search_region

        area_danji_name = str(item.get("areaDanjiName", "")).strip()
        dong_name = str(item.get("dong", "")).strip()
        detail_address = (
            " ".join(part for part in (area_danji_name, dong_name) if part) or None
        )

        item_title = str(item.get("itemTitle", "")).strip()
        description = item_title or None

        return ListingUpsert(
            source="zigbang",
            source_id=source_id,
            property_type="apt",
            rent_type=rent_type,
            deposit=_to_int(item.get("depositMin"), 0),
            monthly_rent=_to_int(item.get("rentMin"), 0),
            address=address,
            dong=dong,
            detail_address=detail_address,
            area_m2=_to_decimal(item.get("sizeM2") or item.get("sizeContractM2")),
            floor=_to_optional_int(item.get("floor")),
            total_floors=None,
            description=description,
            latitude=None,
            longitude=None,
        )

    async def run(self) -> CrawlResult[ListingUpsert]:
        """Fetch and parse Zigbang rental listings."""

        all_rows: list[ListingUpsert] = []
        errors: list[str] = []
        raw_item_count = 0
        parsed_count = 0
        invalid_count = 0
        self._retry_count = 0
        self._cooldown_count = 0
        schema_keys_sample: list[list[str]] = []
        source_keys_sample: list[list[str]] = []
        seen_schema_keys: set[tuple[str, ...]] = set()
        seen_source_keys: set[tuple[str, ...]] = set()
        seen_search_item_ids: set[str] = set()
        seen_listing_source_ids: set[str] = set()

        if not self._region_names:
            logger.warning("No region_names configured - returning empty result")
            self.last_run_metrics = {
                "raw_count": 0,
                "parsed_count": 0,
                "invalid_count": 0,
                "retry_count": 0,
                "cooldown_count": 0,
                "schema_keys_sample": [],
                "source_keys_sample": [],
            }
            return CrawlResult(count=0, rows=[], errors=[])

        timeout = httpx.Timeout(settings.public_data_request_timeout_seconds)

        async with httpx.AsyncClient(timeout=timeout, headers=self._headers) as client:
            for region_idx, region_name in enumerate(self._region_names):
                region_code: str | None = None
                if self._region_codes and region_idx < len(self._region_codes):
                    maybe_code = self._region_codes[region_idx].strip()
                    if maybe_code:
                        region_code = maybe_code

                for property_type in self._property_types:
                    if property_type == "아파트" and region_code:
                        await asyncio.sleep(self._base_delay_seconds)
                        apt_results = await self._fetch_apt_item_catalogs(
                            client, region_code
                        )
                        if not apt_results:
                            continue

                        raw_item_count += len(apt_results)

                        for item in apt_results:
                            top_level_keys = tuple(sorted(item.keys()))
                            if (
                                top_level_keys
                                and top_level_keys not in seen_schema_keys
                                and len(schema_keys_sample) < 3
                            ):
                                seen_schema_keys.add(top_level_keys)
                                schema_keys_sample.append(list(top_level_keys))

                            tran_type = str(item.get("tranType", "")).strip().lower()
                            if tran_type == "trade":
                                continue

                            row = self._parse_apt_catalog_item(item, region_name)
                            if row is None:
                                invalid_count += 1
                                continue

                            if row.source_id in seen_listing_source_ids:
                                continue

                            seen_listing_source_ids.add(row.source_id)
                            all_rows.append(row)
                            parsed_count += 1

                        logger.info(
                            "Fetched %s apartment catalog items for region_name=%s, region_code=%s",
                            len(apt_results),
                            region_name,
                            region_code,
                        )
                        if all_rows and len(all_rows) % 20 == 0:
                            await asyncio.sleep(self._base_delay_seconds * 2)
                        continue

                    for rent_type in ["전세", "월세"]:
                        await asyncio.sleep(self._base_delay_seconds)

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

                            source_id = _extract_source_id(item)
                            if source_id:
                                if source_id in seen_search_item_ids:
                                    continue
                                seen_search_item_ids.add(source_id)

                            row = self._parse_item(item, region_name)
                            if row:
                                if row.source_id in seen_listing_source_ids:
                                    continue
                                seen_listing_source_ids.add(row.source_id)
                                all_rows.append(row)
                                parsed_count += 1
                                continue

                            if not source_id:
                                invalid_count += 1
                                continue

                            detail_payload = await self._fetch_item_details(
                                client, source_id
                            )
                            if detail_payload is None:
                                invalid_count += 1
                                continue

                            parsed_detail_row: ListingUpsert | None = None
                            for detail_item in _extract_detail_listing_candidates(
                                detail_payload
                            ):
                                parsed_detail_row = self._parse_item(
                                    detail_item, region_name
                                )
                                if parsed_detail_row:
                                    break

                            if parsed_detail_row:
                                if parsed_detail_row.source_id in seen_listing_source_ids:
                                    continue
                                seen_listing_source_ids.add(parsed_detail_row.source_id)
                                all_rows.append(parsed_detail_row)
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

                        if all_rows and len(all_rows) % 20 == 0:
                            await asyncio.sleep(self._base_delay_seconds * 2)

        self.last_run_metrics = {
            "raw_count": raw_item_count,
            "parsed_count": parsed_count,
            "invalid_count": invalid_count,
            "retry_count": self._retry_count,
            "cooldown_count": self._cooldown_count,
            "schema_keys_sample": schema_keys_sample,
            "source_keys_sample": source_keys_sample,
        }

        if raw_item_count > 0 and parsed_count == 0:
            mismatch_message = f"Zigbang schema mismatch: raw items fetched but no valid listings parsed (raw_count={raw_item_count}, parsed_count={parsed_count}, invalid_count={invalid_count}, schema_keys_sample={schema_keys_sample}, source_keys_sample={source_keys_sample})"
            raise ZigbangSchemaMismatchError(mismatch_message)

        logger.info(f"Total fetched {len(all_rows)} listings with {len(errors)} errors")

        return CrawlResult(count=len(all_rows), rows=all_rows, errors=errors)
