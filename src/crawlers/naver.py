from __future__ import annotations

import asyncio
import random
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
from typing import Any, Final

import httpx

from src.config import get_settings
from src.crawlers.base import CrawlResult
from src.db.repositories import ListingUpsert

settings = get_settings()

BASE_URL: Final = "https://new.land.naver.com/api"
TRADE_TYPES: Final[tuple[str, str]] = ("B1", "B2")
DEFAULT_MAX_RETRIES: Final = 4
DEFAULT_BASE_DELAY_SECONDS: Final = 1.0
DEFAULT_MAX_BACKOFF_SECONDS: Final = 12.0
DEFAULT_JITTER_RATIO: Final = 0.2

DEFAULT_PROPERTY_TYPES: Final[list[str]] = ["APT", "VILLA", "OPST", "ONEROOM"]
PROPERTY_TYPE_INPUT_MAP: Final[dict[str, str]] = {
    "apt": "APT",
    "villa": "VILLA",
    "officetel": "OPST",
    "house": "ONEROOM",
    "oneroom": "ONEROOM",
    "아파트": "APT",
    "빌라": "VILLA",
    "연립": "VILLA",
    "오피스텔": "OPST",
    "원룸": "ONEROOM",
}
PROPERTY_TYPE_TO_CANONICAL: Final[dict[str, str]] = {
    "APT": "apt",
    "VILLA": "villa",
    "OPST": "officetel",
    "ONEROOM": "house",
}


def _to_int(value: object | None, default: int = 0) -> int:
    if value is None:
        return default
    if isinstance(value, (int, float, Decimal)):
        return int(value)

    cleaned = str(value).replace(",", "").replace(" ", "").strip()
    if not cleaned:
        return default

    if "/" in cleaned:
        cleaned = cleaned.split("/", 1)[0]

    digits = "".join(ch for ch in cleaned if ch.isdigit())
    if not digits:
        return default
    return int(digits)


def _to_optional_decimal(value: object | None) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))

    cleaned = str(value).replace(",", "").replace(" ", "").strip()
    if not cleaned:
        return None

    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _parse_retry_after_seconds(value: str) -> float | None:
    retry_after = value.strip()
    if not retry_after:
        return None

    if retry_after.isdigit():
        return max(0.0, float(int(retry_after)))

    try:
        retry_after_dt = parsedate_to_datetime(retry_after)
    except (TypeError, ValueError):
        return None

    if retry_after_dt.tzinfo is None:
        retry_after_dt = retry_after_dt.replace(tzinfo=timezone.utc)

    delay = (retry_after_dt - datetime.now(timezone.utc)).total_seconds()
    return max(0.0, delay)


def _normalize_property_type_code(value: str) -> str:
    text = value.strip()
    if not text:
        return "APT"

    upper = text.upper()
    if upper in PROPERTY_TYPE_TO_CANONICAL:
        return upper

    return PROPERTY_TYPE_INPUT_MAP.get(text.lower(), "APT")


def _map_property_type(raw_value: str) -> str:
    code = _normalize_property_type_code(raw_value)
    return PROPERTY_TYPE_TO_CANONICAL.get(code, "apt")


def _map_rent_type(raw_value: str) -> str:
    text = raw_value.strip()
    upper = text.upper()
    if upper == "B1" or "전세" in text:
        return "jeonse"
    if upper == "B2" or "월세" in text:
        return "monthly"
    return "monthly"


def _parse_floor(value: object | None) -> int | None:
    if value is None:
        return None

    text = str(value).strip()
    if not text:
        return None

    first_part = text.split("/", 1)[0].strip()
    if not first_part:
        return None

    match = re.fullmatch(r"B\s*(\d+)", first_part.upper())
    if match:
        return -int(match.group(1))

    match = re.fullmatch(r"지하\s*(\d+)", first_part)
    if match:
        return -int(match.group(1))

    if re.fullmatch(r"[+-]?\d+", first_part):
        return int(first_part)

    return None


def _parse_total_floors(value: object | None) -> int | None:
    if value is None:
        return None

    text = str(value).strip()
    if "/" not in text:
        return None

    total_part = text.split("/", 1)[1].strip()
    if not total_part:
        return None

    digits = "".join(ch for ch in total_part if ch.isdigit())
    if not digits:
        return None
    return int(digits)


class NaverCrawler:
    def __init__(
        self,
        region_codes: list[str] | None = None,
        property_types: list[str] | None = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_delay_seconds: float = DEFAULT_BASE_DELAY_SECONDS,
        max_backoff_seconds: float = DEFAULT_MAX_BACKOFF_SECONDS,
    ) -> None:
        self._region_codes = region_codes or list(settings.target_region_codes)

        raw_property_types = property_types or list(settings.target_property_types)
        if raw_property_types:
            self._property_types = [
                _normalize_property_type_code(str(item)) for item in raw_property_types
            ]
        else:
            self._property_types = list(DEFAULT_PROPERTY_TYPES)

        self._max_retries = max(0, max_retries)
        self._base_delay_seconds = max(0.0, base_delay_seconds)
        self._max_backoff_seconds = max(self._base_delay_seconds, max_backoff_seconds)
        self._jitter_ratio = max(0.0, DEFAULT_JITTER_RATIO)

        self._headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            "Referer": "https://new.land.naver.com/articles",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            "sec-ch-ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"macOS"',
        }

    def _apply_jitter(self, base_seconds: float) -> float:
        if base_seconds <= 0:
            return 0.0
        ratio = random.uniform(-self._jitter_ratio, self._jitter_ratio)
        return max(0.0, base_seconds * (1 + ratio))

    def _effective_retry_delay(self, response: httpx.Response, attempt: int) -> float:
        retry_after = response.headers.get("Retry-After")
        if retry_after is not None:
            parsed = _parse_retry_after_seconds(retry_after)
            if parsed is not None:
                return parsed

        base = min(
            self._base_delay_seconds * (2**attempt),
            self._max_backoff_seconds,
        )
        return self._apply_jitter(base)

    def _parse_article(
        self,
        article: dict[str, object],
        region_code: str,
    ) -> ListingUpsert | None:
        article_no = str(article.get("articleNo", "")).strip()
        if not article_no:
            return None

        property_type = _map_property_type(
            str(
                article.get("realEstateType")
                or article.get("realEstateTypeName")
                or "APT"
            )
        )
        rent_type = _map_rent_type(
            str(article.get("tradeType") or article.get("tradeTypeName") or "B2")
        )

        raw_deal = article.get("dealOrWarrantPrc")
        if raw_deal is None or str(raw_deal).strip() == "":
            raw_deal = article.get("price1")
        deposit = _to_int(raw_deal, 0)
        raw_rent = article.get("rentPrc")
        if raw_rent is None or str(raw_rent).strip() == "":
            raw_rent = article.get("price2")
        monthly_rent = _to_int(raw_rent, 0)
        if monthly_rent == 0 and isinstance(raw_deal, str) and "/" in raw_deal:
            monthly_rent = _to_int(raw_deal.split("/", 1)[1], 0)

        address = str(
            article.get("address")
            or article.get("jibunAddress")
            or article.get("roadAddress")
            or article.get("articleName")
            or region_code
        ).strip()
        dong = str(
            article.get("dongName")
            or article.get("divisionName")
            or article.get("cityName")
            or article.get("dong")
            or region_code
        ).strip()
        detail_address = str(
            article.get("detailAddress")
            or article.get("articleName")
            or article.get("buildingName")
            or ""
        ).strip()
        description = (
            str(article.get("articleFeatureDesc") or article.get("description") or "")
            .strip()
            or None
        )
        floor_info = article.get("floorInfo")

        return ListingUpsert(
            source="naver",
            source_id=article_no,
            property_type=property_type,
            rent_type=rent_type,
            deposit=deposit,
            monthly_rent=monthly_rent,
            address=address,
            dong=dong,
            detail_address=detail_address or None,
            area_m2=_to_optional_decimal(article.get("area1") or article.get("area2")),
            floor=_parse_floor(floor_info),
            total_floors=_parse_total_floors(floor_info),
            description=description,
            latitude=_to_optional_decimal(
                article.get("latitude") or article.get("lat")
            ),
            longitude=_to_optional_decimal(
                article.get("longitude") or article.get("lng")
            ),
        )

    async def _request_articles_with_client(
        self,
        *,
        client: httpx.AsyncClient,
        region_code: str,
        property_type: str,
        trade_type: str,
    ) -> list[dict[str, Any]]:
        for attempt in range(self._max_retries + 1):
            response = await client.get(
                f"{BASE_URL}/articles",
                params={
                    "cortarNo": region_code,
                    "realEstateType": property_type,
                    "tradeType": trade_type,
                },
            )

            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code != 429:
                    raise
                if attempt >= self._max_retries:
                    raise
                await asyncio.sleep(self._effective_retry_delay(exc.response, attempt))
                continue

            payload = response.json()
            if isinstance(payload, dict):
                if payload.get("success") is False:
                    return []
                article_list = payload.get("articleList")
                if isinstance(article_list, list):
                    return [item for item in article_list if isinstance(item, dict)]
            return []

        return []

    async def _request_articles(
        self,
        *,
        region_code: str,
        property_type: str,
        trade_type: str,
    ) -> list[dict[str, Any]]:
        timeout = httpx.Timeout(settings.public_data_request_timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout, headers=self._headers) as client:
            return await self._request_articles_with_client(
                client=client,
                region_code=region_code,
                property_type=property_type,
                trade_type=trade_type,
            )

    async def run(self) -> CrawlResult[ListingUpsert]:
        all_rows: list[ListingUpsert] = []
        errors: list[str] = []

        timeout = httpx.Timeout(settings.public_data_request_timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout, headers=self._headers) as client:
            for region_code in self._region_codes:
                for property_type in self._property_types:
                    for trade_type in TRADE_TYPES:
                        await asyncio.sleep(self._base_delay_seconds)
                        try:
                            articles = await self._request_articles_with_client(
                                client=client,
                                region_code=region_code,
                                property_type=property_type,
                                trade_type=trade_type,
                            )
                        except httpx.HTTPStatusError as exc:
                            errors.append(
                                "HTTP "
                                f"{exc.response.status_code} exhausted retries "
                                f"for region_code={region_code}, "
                                f"property_type={property_type}, "
                                f"trade_type={trade_type}"
                            )
                            return CrawlResult(
                                count=len(all_rows), rows=all_rows, errors=errors
                            )
                        except Exception as exc:  # noqa: BLE001
                            errors.append(
                                f"Unexpected error for region_code={region_code}, "
                                f"property_type={property_type}, trade_type={trade_type}: {exc}"
                            )
                            return CrawlResult(
                                count=len(all_rows), rows=all_rows, errors=errors
                            )

                        for article in articles:
                            row = self._parse_article(article, region_code)
                            if row is not None:
                                all_rows.append(row)

        return CrawlResult(count=len(all_rows), rows=all_rows, errors=errors)
