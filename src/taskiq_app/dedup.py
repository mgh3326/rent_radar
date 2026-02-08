"""Redis-based dedup helpers for crawl enqueue and execution."""

from __future__ import annotations

from time import monotonic

from redis.asyncio import Redis

from src.config import get_settings

_MEMORY_LOCKS: dict[str, float] = {}


def build_dedup_key(*, scope: str, task_name: str, fingerprint: str) -> str:
    """Build namespaced dedup key."""

    return f"dedup:{scope}:{task_name}:{fingerprint}"


def _acquire_memory_lock(key: str, ttl_seconds: int) -> bool:
    now = monotonic()
    expired = [lock_key for lock_key, expiry in _MEMORY_LOCKS.items() if expiry <= now]
    for lock_key in expired:
        _MEMORY_LOCKS.pop(lock_key, None)

    if key in _MEMORY_LOCKS:
        return False

    _MEMORY_LOCKS[key] = now + ttl_seconds
    return True


async def acquire_dedup_lock(key: str, ttl_seconds: int) -> bool:
    """Acquire distributed lock via Redis SET NX EX semantics."""

    settings = get_settings()

    if settings.taskiq_testing:
        return _acquire_memory_lock(key, ttl_seconds)

    client = Redis.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
    try:
        locked = await client.set(key, "1", nx=True, ex=ttl_seconds)
        return bool(locked)
    finally:
        await client.aclose()


async def release_dedup_lock(key: str) -> None:
    """Release distributed lock by deleting the key."""

    settings = get_settings()

    if settings.taskiq_testing:
        _MEMORY_LOCKS.pop(key, None)
        return

    client = Redis.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
    try:
        await client.delete(key)
    finally:
        await client.aclose()
