"""Taskiq tasks for crawling and ingestion."""

import logging
from typing import Any, cast

from src.config import get_settings
from src.crawlers.zigbang import ZigbangCrawler
from src.db.repositories import (
    ListingUpsert,
    deactivate_stale_listings,
    upsert_listings,
)
from src.db.session import session_context
from src.notifications.telegram import TelegramNotifier
from src.taskiq_app.broker import broker
from src.taskiq_app.dedup import (
    acquire_dedup_lock,
    build_dedup_key,
    release_dedup_lock,
)

logger = logging.getLogger(__name__)
settings = get_settings()


async def _persist_listings(rows: list[ListingUpsert]) -> int:
    """Persist crawled listing rows with duplicate-safe insert semantics."""

    async with session_context() as session:
        return await upsert_listings(session, rows)


@broker.task(
    task_name="crawl_zigbang_listings",
    schedule=[{"cron": "30 */6 * * *"}],
    retry_on_error=True,
    max_retries=3,
)
async def crawl_zigbang_listings() -> dict[str, object]:
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

    try:
        crawler = ZigbangCrawler(region_codes=list(settings.target_region_codes))
        result = await crawler.run()
        inserted = await _persist_listings(result.rows)

        async with session_context() as session:
            deactivated = await deactivate_stale_listings(session, "zigbang", 48)

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
    finally:
        await release_dedup_lock(dedup_key)


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


@broker.task(
    task_name="monitor_favorites",
    schedule=[{"cron": "0 */12 * * *"}],
    retry_on_error=True,
    max_retries=3,
)
async def monitor_favorites() -> dict[str, object]:
    from sqlalchemy import select, update

    from src.db.repositories import PriceChangeUpsert, upsert_price_changes
    from src.models.favorite import Favorite
    from src.models.listing import Listing

    dedup_key = build_dedup_key(
        scope="execution", task_name="monitor_favorites", fingerprint="default"
    )
    lock_acquired = await acquire_dedup_lock(
        dedup_key, settings.crawl_dedup_ttl_seconds
    )
    if not lock_acquired:
        logger.info("monitor_favorites skipped due to dedup lock")
        return {"status": "skipped_duplicate_execution", "changes_detected": 0}

    try:
        async with session_context() as session:
            stmt = (
                select(Favorite, Listing)
                .join(Listing, Favorite.listing_id == Listing.id)
                .where(Listing.is_active)
            )
            result = await session.execute(stmt)
            rows = result.all()

            price_changes: list[PriceChangeUpsert] = []
            notifications: list[str] = []
            favorites_to_update: list[int] = []

            for favorite, listing in rows:
                old_deposit = favorite.deposit_at_save
                old_monthly_rent = favorite.monthly_rent_at_save

                if old_deposit is None or old_monthly_rent is None:
                    continue

                if (
                    old_deposit != listing.deposit
                    or old_monthly_rent != listing.monthly_rent
                ):
                    price_changes.append(
                        PriceChangeUpsert(
                            listing_id=listing.id,
                            old_deposit=old_deposit,
                            old_monthly_rent=old_monthly_rent,
                            new_deposit=listing.deposit,
                            new_monthly_rent=listing.monthly_rent,
                        )
                    )
                    change_desc = f"매물 #{listing.id}: 보증금 {old_deposit:,}→{listing.deposit:,}"
                    if old_monthly_rent != listing.monthly_rent:
                        change_desc += (
                            f", 월세 {old_monthly_rent:,}→{listing.monthly_rent:,}"
                        )
                    notifications.append(change_desc)
                    favorites_to_update.append(favorite.id)

            if price_changes:
                await upsert_price_changes(session, price_changes)

            if favorites_to_update:
                listing_map = {
                    favorite_obj: listing_obj
                    for favorite_obj, listing_obj in rows
                    if favorite_obj.id in favorites_to_update
                }
                for fav_id in favorites_to_update:
                    fav = next((f for f, _ in rows if f.id == fav_id), None)
                    lst = listing_map.get(fav)
                    if fav and lst:
                        stmt_update = (
                            update(Favorite)
                            .where(Favorite.id == fav.id)
                            .values(
                                deposit_at_save=lst.deposit,
                                monthly_rent_at_save=lst.monthly_rent,
                            )
                        )
                        await session.execute(stmt_update)
                await session.commit()

            if notifications:
                notifier = TelegramNotifier()
                message = "관심매물 가격 변동 알림\n\n" + "\n".join(notifications)
                await notifier.send(message, title="가격 변동 감지")

            return {
                "status": "ok",
                "favorites_checked": len(rows),
                "changes_detected": len(price_changes),
                "notifications_sent": len(notifications),
            }
    finally:
        await release_dedup_lock(dedup_key)
