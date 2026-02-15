"""Redis cache helpers for listing search results."""

import hashlib
import json
from typing import Any, cast

from redis.asyncio import Redis

from src.config import get_settings

settings = get_settings()


def build_search_cache_key(
    region_code: str | None,
    dong: str | None,
    property_type: str | None,
    rent_type: str | None,
    min_deposit: int | None,
    max_deposit: int | None,
    min_monthly_rent: int | None,
    max_monthly_rent: int | None,
    min_area: float | None,
    max_area: float | None,
    min_floor: int | None,
    max_floor: int | None,
    source: str | None,
    limit: int,
) -> str:
    filters = {
        "region_code": region_code or "",
        "dong": dong or "",
        "property_type": property_type or "",
        "rent_type": rent_type or "",
        "min_deposit": min_deposit,
        "max_deposit": max_deposit,
        "min_monthly_rent": min_monthly_rent,
        "max_monthly_rent": max_monthly_rent,
        "min_area": f"{min_area:.6f}" if min_area is not None else None,
        "max_area": f"{max_area:.6f}" if max_area is not None else None,
        "min_floor": min_floor,
        "max_floor": max_floor,
        "source": source or "",
        "limit": limit,
    }
    data = json.dumps(filters, sort_keys=True)
    hash_val = hashlib.md5(data.encode()).hexdigest()[:16]
    return f"search:rent:{hash_val}"


async def cache_get(key: str) -> str | None:
    client = Redis.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
    try:
        value = await client.get(key)
        return cast(str, value) if value else None
    finally:
        await client.aclose()


async def cache_set(key: str, value: Any, ttl_seconds: int) -> None:
    json_value = json.dumps(value)
    client = Redis.from_url(settings.redis_url, encoding="utf-8")
    try:
        await client.set(key, json_value, ex=ttl_seconds)
    finally:
        await client.aclose()


async def cache_delete(key: str) -> None:
    client = Redis.from_url(settings.redis_url, encoding="utf-8")
    try:
        await client.delete(key)
    finally:
        await client.aclose()
