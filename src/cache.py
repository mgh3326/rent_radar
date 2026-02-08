"""Redis cache helpers for listing search results."""

import hashlib
import json
from typing import Any, cast

from redis.asyncio import Redis

from src.config import get_settings

settings = get_settings()


async def cache_get(key: str) -> str | None:
    """Get value from Redis cache."""

    client = Redis.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
    try:
        value = await client.get(key)
        return cast(str, value) if value else None
    finally:
        await client.aclose()


async def cache_set(key: str, value: Any, ttl_seconds: int) -> None:
    """Set value in Redis cache with TTL."""

    json_value = json.dumps(value)
    client = Redis.from_url(settings.redis_url, encoding="utf-8")
    try:
        await client.set(key, json_value, ex=ttl_seconds)
    finally:
        await client.aclose()


async def cache_delete(key: str) -> None:
    """Delete value from Redis cache."""

    client = Redis.from_url(settings.redis_url, encoding="utf-8")
    try:
        await client.delete(key)
    finally:
        await client.aclose()
