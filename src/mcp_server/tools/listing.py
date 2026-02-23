"""MCP tools for rental listing search."""

import json
from decimal import Decimal
from typing import cast

from mcp.server.fastmcp import FastMCP

from src.cache import build_search_cache_key, cache_get, cache_set
from src.config import get_settings
from src.db.session import session_context
from src.services.listing_service import ListingService

settings = get_settings()
EMPTY_RESULTS_MESSAGE = (
    "활성 매물은 listings 데이터 기준이며, 실거래 데이터(real_trades)와는 별개입니다."
)
CRAWL_STATUS_SOURCE = "zigbang"
CRAWL_STALE_THRESHOLD_HOURS = 48
CRAWL_NEEDED_MESSAGE = (
    "해당 지역의 zigbang 매물 데이터가 없거나 오래되어 크롤링이 필요합니다."
)


def register_listing_tools(mcp: FastMCP) -> None:
    """Register listing-related tools on a FastMCP server."""

    @mcp.tool(name="search_rent")
    async def search_rent(
        region_code: str | None = None,
        dong: str | None = None,
        property_type: str | None = None,
        rent_type: str | None = None,
        min_deposit: int | None = None,
        max_deposit: int | None = None,
        min_monthly_rent: int | None = None,
        max_monthly_rent: int | None = None,
        min_area: float | None = None,
        max_area: float | None = None,
        min_floor: int | None = None,
        max_floor: int | None = None,
        limit: int = 50,
    ) -> dict[str, object]:
        async def evaluate_crawl_status() -> dict[str, object]:
            async with session_context() as session:
                service = ListingService(session)
                return await service.evaluate_crawl_status(
                    region_code=region_code,
                    stale_hours=CRAWL_STALE_THRESHOLD_HOURS,
                    source=CRAWL_STATUS_SOURCE,
                )

        cache_key = build_search_cache_key(
            region_code=region_code,
            dong=dong,
            property_type=property_type,
            rent_type=rent_type,
            min_deposit=min_deposit,
            max_deposit=max_deposit,
            min_monthly_rent=min_monthly_rent,
            max_monthly_rent=max_monthly_rent,
            min_area=min_area,
            max_area=max_area,
            min_floor=min_floor,
            max_floor=max_floor,
            source=None,
            limit=limit,
        )

        cached = await cache_get(cache_key)
        if cached:
            result = cast(dict[str, object], json.loads(cached))
            if result.get("count") == 0 and "message" not in result:
                result["message"] = EMPTY_RESULTS_MESSAGE
            result["cache_hit"] = True

            crawl_status = await evaluate_crawl_status()
            result["crawl_status"] = crawl_status
            if crawl_status.get("needs_crawl") is True:
                result["crawl_message"] = CRAWL_NEEDED_MESSAGE
            else:
                result.pop("crawl_message", None)
            return result

        async with session_context() as session:
            service = ListingService(session)
            results = await service.search_listings(
                region_code=region_code,
                dong=dong,
                property_type=property_type,
                rent_type=rent_type,
                min_deposit=min_deposit,
                max_deposit=max_deposit,
                min_monthly_rent=min_monthly_rent,
                max_monthly_rent=max_monthly_rent,
                min_area=Decimal(str(min_area)) if min_area is not None else None,
                max_area=Decimal(str(max_area)) if max_area is not None else None,
                min_floor=min_floor,
                max_floor=max_floor,
                is_active=True,
                limit=limit,
            )
            crawl_status = await service.evaluate_crawl_status(
                region_code=region_code,
                stale_hours=CRAWL_STALE_THRESHOLD_HOURS,
                source=CRAWL_STATUS_SOURCE,
            )

        result: dict[str, object] = {
            "query": {
                "region_code": region_code,
                "dong": dong,
                "property_type": property_type,
                "rent_type": rent_type,
                "min_deposit": min_deposit,
                "max_deposit": max_deposit,
                "min_monthly_rent": min_monthly_rent,
                "max_monthly_rent": max_monthly_rent,
                "min_area": min_area,
                "max_area": max_area,
                "min_floor": min_floor,
                "max_floor": max_floor,
                "limit": limit,
            },
            "count": len(results),
            "items": results,
            "cache_hit": False,
            "crawl_status": crawl_status,
        }
        if result["count"] == 0:
            result["message"] = EMPTY_RESULTS_MESSAGE
        if crawl_status.get("needs_crawl") is True:
            result["crawl_message"] = CRAWL_NEEDED_MESSAGE

        await cache_set(cache_key, result, settings.listing_cache_ttl_seconds)
        return result
