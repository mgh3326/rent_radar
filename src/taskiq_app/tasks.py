"""Taskiq tasks for crawling and ingestion."""

import logging
from typing import Any, cast

from src.config import get_settings

logger = logging.getLogger(__name__)
from src.crawlers.naver import NaverCrawler
from src.crawlers.public_api import PublicApiCrawler
from src.crawlers.zigbang import ZigbangCrawler
from src.db.repositories import (
    ListingUpsert,
    RealTradeUpsert,
    deactivate_stale_listings,
    upsert_listings,
    upsert_real_trades,
)
from src.db.session import session_context
from src.notifications.telegram import TelegramNotifier
from src.taskiq_app.broker import broker
from src.taskiq_app.dedup import acquire_dedup_lock, build_dedup_key

settings = get_settings()


async def _persist_real_trades(rows: list[RealTradeUpsert]) -> int:
    """Persist crawled rows with duplicate-safe insert semantics."""

    async with session_context() as session:
        return await upsert_real_trades(session, rows)


async def _persist_listings(rows: list[ListingUpsert]) -> int:
    """Persist crawled listing rows with duplicate-safe insert semantics."""

    async with session_context() as session:
        return await upsert_listings(session, rows)


@broker.task(
    task_name="crawl_real_trade",
    schedule=[{"cron": "0 3 * * *"}],
    retry_on_error=True,
    max_retries=3,
)
async def crawl_real_trade() -> dict[str, object]:
    """Crawl public apartment rent API and persist real trade rows."""

    dedup_key = build_dedup_key(
        scope="execution", task_name="crawl_real_trade", fingerprint="default"
    )
    lock_acquired = await acquire_dedup_lock(
        dedup_key, settings.crawl_dedup_ttl_seconds
    )
    if not lock_acquired:
        logger.info("crawl_real_trade skipped due to dedup lock")
        return {
            "source": "public_api",
            "count": 0,
            "status": "skipped_duplicate_execution",
        }

    crawler = PublicApiCrawler()
    result = await crawler.run()
    inserted = await _persist_real_trades(result.rows)

    # Send notification on successful crawl
    if inserted > 0:
        notifier = TelegramNotifier()
        message = f"매매/전월세 데이터 수집 완료\n\n총 {inserted}건 데이터 저장됨 (수집: {result.count}건)"
        await notifier.send(message, title="공공데이터 크롤링 완료")

    return {
        "source": "public_api",
        "count": inserted,
        "fetched": result.count,
        "status": "ok",
    }


async def enqueue_crawl_real_trade(*, fingerprint: str = "manual") -> dict[str, object]:
    """Enqueue crawl task once per dedup window using SET NX EX semantics."""

    dedup_key = build_dedup_key(
        scope="enqueue", task_name="crawl_real_trade", fingerprint=fingerprint
    )
    lock_acquired = await acquire_dedup_lock(
        dedup_key, settings.crawl_dedup_ttl_seconds
    )
    if not lock_acquired:
        return {"enqueued": False, "reason": "duplicate_enqueue"}

    task_kicker = cast(Any, crawl_real_trade)
    task = await task_kicker.kiq()
    return {"enqueued": True, "task_id": task.task_id}


@broker.task(
    task_name="crawl_naver_listings",
    schedule=[{"cron": "0 */6 * * *"}],
    retry_on_error=True,
    max_retries=3,
)
async def crawl_naver_listings() -> dict[str, object]:
    """Crawl Naver Real Estate listings and persist them."""

    dedup_key = build_dedup_key(
        scope="execution", task_name="crawl_naver_listings", fingerprint="default"
    )
    lock_acquired = await acquire_dedup_lock(
        dedup_key, settings.crawl_dedup_ttl_seconds
    )
    if not lock_acquired:
        logger.info("crawl_naver_listings skipped due to dedup lock")
        return {
            "source": "naver",
            "count": 0,
            "status": "skipped_duplicate_execution",
        }

    crawler = NaverCrawler()
    result = await crawler.run()
    inserted = await _persist_listings(result.rows)

    # Deactivate stale listings
    async with session_context() as session:
        deactivated = await deactivate_stale_listings(session, "naver", 48)

    # Send notification on successful crawl
    if inserted > 0:
        notifier = TelegramNotifier()
        message = f"네이버 부동산 매물 수집 완료\n\n총 {inserted}건 신규 매물 저장됨 (수집: {result.count}건, {deactivated}건 비활성화)"
        await notifier.send(message, title="네이버 매물 크롤링 완료")

    return {
        "source": "naver",
        "count": inserted,
        "fetched": result.count,
        "deactivated": deactivated,
        "status": "ok",
    }


@broker.task(
    task_name="crawl_zigbang_listings",
    schedule=[{"cron": "30 */6 * * *"}],
    retry_on_error=True,
    max_retries=3,
)
async def crawl_zigbang_listings() -> dict[str, object]:
    """Crawl Zigbang rental listings and persist them."""

    dedup_key = build_dedup_key(
        scope="execution", task_name="crawl_zigbang_listings", fingerprint="default"
    )
    lock_acquired = await acquire_dedup_lock(
        dedup_key, settings.crawl_dedup_ttl_seconds
    )
    if not lock_acquired:
        logger.info("crawl_zigbang_listings skipped due to dedup lock")
        return {
            "source": "zigbang",
            "count": 0,
            "status": "skipped_duplicate_execution",
        }

    crawler = ZigbangCrawler()
    result = await crawler.run()
    inserted = await _persist_listings(result.rows)

    # Deactivate stale listings
    async with session_context() as session:
        deactivated = await deactivate_stale_listings(session, "zigbang", 48)

    # Send notification on successful crawl
    if inserted > 0:
        notifier = TelegramNotifier()
        message = f"직방 매물 수집 완료\n\n총 {inserted}건 신규 매물 저장됨 (수집: {result.count}건, {deactivated}건 비활성화)"
        await notifier.send(message, title="직방 매물 크롤링 완료")

    return {
        "source": "zigbang",
        "count": inserted,
        "fetched": result.count,
        "deactivated": deactivated,
        "status": "ok",
    }


async def enqueue_crawl_naver_listings(
    *, fingerprint: str = "manual"
) -> dict[str, object]:
    """Enqueue Naver crawl task once per dedup window."""

    dedup_key = build_dedup_key(
        scope="enqueue", task_name="crawl_naver_listings", fingerprint=fingerprint
    )
    lock_acquired = await acquire_dedup_lock(
        dedup_key, settings.crawl_dedup_ttl_seconds
    )
    if not lock_acquired:
        return {"enqueued": False, "reason": "duplicate_enqueue"}

    task_kicker = cast(Any, crawl_naver_listings)
    task = await task_kicker.kiq()
    return {"enqueued": True, "task_id": task.task_id}


async def enqueue_crawl_zigbang_listings(
    *, fingerprint: str = "manual"
) -> dict[str, object]:
    """Enqueue Zigbang crawl task once per dedup window."""

    dedup_key = build_dedup_key(
        scope="enqueue", task_name="crawl_zigbang_listings", fingerprint=fingerprint
    )
    lock_acquired = await acquire_dedup_lock(
        dedup_key, settings.crawl_dedup_ttl_seconds
    )
    if not lock_acquired:
        return {"enqueued": False, "reason": "duplicate_enqueue"}

    task_kicker = cast(Any, crawl_zigbang_listings)
    task = await task_kicker.kiq()
    return {"enqueued": True, "task_id": task.task_id}
