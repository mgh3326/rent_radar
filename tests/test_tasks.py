from __future__ import annotations

from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Any, cast

import pytest

import src.taskiq_app.tasks as task_module
from src.crawlers.base import CrawlResult
from src.crawlers.zigbang import ZigbangSchemaMismatchError
from src.db.repositories import ListingUpsert
from src.taskiq_app.tasks import (
    crawl_zigbang_listings,
    enqueue_crawl_zigbang_listings,
)


def _sample_listing() -> ListingUpsert:
    return ListingUpsert(
        source="zigbang",
        source_id="zb-1001",
        property_type="apt",
        rent_type="jeonse",
        deposit=58000,
        monthly_rent=0,
        address="서울특별시 종로구 사직동 1-1",
        dong="사직동",
        detail_address="101동 1201호",
        area_m2=Decimal("59.99"),
        floor=12,
        total_floors=20,
        description="테스트 매물",
        latitude=Decimal("37.575"),
        longitude=Decimal("126.973"),
    )


@pytest.mark.anyio
async def test_removed_task_paths_not_exposed() -> None:
    assert not hasattr(task_module, "crawl_real_trade")
    assert not hasattr(task_module, "enqueue_crawl_real_trade")
    assert not hasattr(task_module, "crawl_naver_listings")
    assert not hasattr(task_module, "enqueue_crawl_naver_listings")


@pytest.mark.anyio
async def test_crawl_zigbang_listings_task_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_run(self: object) -> CrawlResult[ListingUpsert]:
        return CrawlResult(count=1, rows=[_sample_listing()])

    async def fake_persist(rows: list[ListingUpsert]) -> int:
        return len(rows)

    async def fake_lock(key: str, ttl_seconds: int) -> bool:  # noqa: ARG001
        return True

    async def fake_deactivate(
        session: object,
        source: str,
        stale_hours: int,
    ) -> int:
        assert source == "zigbang"
        assert stale_hours == 48
        _ = session
        return 2

    @asynccontextmanager
    async def fake_session_context():
        yield object()

    async def fake_notify(self: object, message: str, title: str = "") -> bool:  # noqa: ARG001
        return True

    monkeypatch.setattr("src.crawlers.zigbang.ZigbangCrawler.run", fake_run)
    monkeypatch.setattr("src.taskiq_app.tasks._persist_listings", fake_persist)
    monkeypatch.setattr("src.taskiq_app.tasks.acquire_dedup_lock", fake_lock)
    monkeypatch.setattr(
        "src.taskiq_app.tasks.deactivate_stale_listings", fake_deactivate
    )
    monkeypatch.setattr("src.taskiq_app.tasks.session_context", fake_session_context)
    monkeypatch.setattr("src.taskiq_app.tasks.TelegramNotifier.send", fake_notify)

    task_fn = cast(Any, crawl_zigbang_listings)
    task = await task_fn.kiq()
    result = await task.wait_result(timeout=30)

    assert not result.is_err
    assert result.return_value["source"] == "zigbang"
    assert result.return_value["fetched"] == 1
    assert result.return_value["count"] == 1
    assert result.return_value["deactivated"] == 2


@pytest.mark.anyio
async def test_enqueue_crawl_zigbang_listings_dedup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class DummyTask:
        task_id: str = "zigbang-task-123"

    async def fake_kiq(*args: object, **kwargs: object):  # noqa: ARG001
        return DummyTask()

    task_fn = cast(Any, crawl_zigbang_listings)
    monkeypatch.setattr(task_fn, "kiq", fake_kiq)

    first = await enqueue_crawl_zigbang_listings(fingerprint="manual-test")
    second = await enqueue_crawl_zigbang_listings(fingerprint="manual-test")

    assert first == {"enqueued": True, "task_id": "zigbang-task-123"}
    assert second == {"enqueued": False, "reason": "duplicate_enqueue"}


@pytest.mark.anyio
async def test_crawl_zigbang_listings_releases_lock_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    released: list[str] = []

    async def fake_run(self: object) -> CrawlResult[ListingUpsert]:
        raise RuntimeError("Simulated zigbang crawler failure")

    async def fake_lock(key: str, ttl_seconds: int) -> bool:  # noqa: ARG001
        return True

    async def fake_release(key: str) -> None:
        released.append(key)

    monkeypatch.setattr("src.crawlers.zigbang.ZigbangCrawler.run", fake_run)
    monkeypatch.setattr("src.taskiq_app.tasks.acquire_dedup_lock", fake_lock)
    monkeypatch.setattr("src.taskiq_app.tasks.release_dedup_lock", fake_release)

    task_fn = cast(Any, crawl_zigbang_listings)
    task = await task_fn.kiq()
    result = await task.wait_result(timeout=30)

    assert result.is_err
    assert released


@pytest.mark.anyio
async def test_crawl_zigbang_schema_mismatch_fails_before_upsert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = {"persist": 0}

    async def fake_run(self: object) -> CrawlResult[ListingUpsert]:
        raise ZigbangSchemaMismatchError("raw_count=5 parsed_count=0")

    async def fake_persist(_rows: list[ListingUpsert]) -> int:
        called["persist"] += 1
        return 0

    async def fake_lock(key: str, ttl_seconds: int) -> bool:  # noqa: ARG001
        return True

    monkeypatch.setattr("src.crawlers.zigbang.ZigbangCrawler.run", fake_run)
    monkeypatch.setattr("src.taskiq_app.tasks._persist_listings", fake_persist)
    monkeypatch.setattr("src.taskiq_app.tasks.acquire_dedup_lock", fake_lock)

    task_fn = cast(Any, crawl_zigbang_listings)
    task = await task_fn.kiq()
    result = await task.wait_result(timeout=30)

    assert result.is_err
    assert called["persist"] == 0
