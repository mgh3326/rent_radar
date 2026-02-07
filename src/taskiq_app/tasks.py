"""Taskiq tasks for crawling and ingestion."""

from typing import Any, cast

from src.config import get_settings
from src.crawlers.public_api import PublicApiCrawler
from src.db.repositories import RealTradeUpsert, upsert_real_trades
from src.db.session import session_context
from src.taskiq_app.broker import broker
from src.taskiq_app.dedup import acquire_dedup_lock, build_dedup_key

settings = get_settings()


async def _persist_real_trades(rows: list[RealTradeUpsert]) -> int:
    """Persist crawled rows with duplicate-safe insert semantics."""

    async with session_context() as session:
        return await upsert_real_trades(session, rows)


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
        return {
            "source": "public_api",
            "count": 0,
            "status": "skipped_duplicate_execution",
        }

    crawler = PublicApiCrawler()
    result = await crawler.run()
    inserted = await _persist_real_trades(result.rows)
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
