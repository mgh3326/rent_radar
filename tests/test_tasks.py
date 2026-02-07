"""Taskiq task tests for public API crawler flow."""

from decimal import Decimal
from typing import Any, cast

import pytest

from src.crawlers.base import CrawlResult
from src.db.repositories import RealTradeUpsert
from src.taskiq_app.tasks import crawl_real_trade, enqueue_crawl_real_trade


@pytest.mark.anyio
async def test_crawl_real_trade_task_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """Task executes crawler and persistence when dedup lock is acquired."""

    sample_row = RealTradeUpsert(
        property_type="apt",
        rent_type="jeonse",
        region_code="11110",
        dong="아현동",
        apt_name="테스트아파트",
        deposit=32000,
        monthly_rent=0,
        area_m2=Decimal("59.99"),
        floor=9,
        contract_year=2026,
        contract_month=1,
        contract_day=10,
    )

    async def fake_run(self: object) -> CrawlResult[RealTradeUpsert]:
        return CrawlResult(count=1, rows=[sample_row])

    async def fake_persist(rows: list[RealTradeUpsert]) -> int:
        return len(rows)

    async def fake_lock(key: str, ttl_seconds: int) -> bool:  # noqa: ARG001
        return True

    monkeypatch.setattr("src.crawlers.public_api.PublicApiCrawler.run", fake_run)
    monkeypatch.setattr("src.taskiq_app.tasks._persist_real_trades", fake_persist)
    monkeypatch.setattr("src.taskiq_app.tasks.acquire_dedup_lock", fake_lock)

    task_fn = cast(Any, crawl_real_trade)
    task = await task_fn.kiq()
    result = await task.wait_result(timeout=30)

    assert not result.is_err
    assert result.return_value["source"] == "public_api"
    assert result.return_value["fetched"] == 1
    assert result.return_value["count"] == 1


@pytest.mark.anyio
async def test_enqueue_crawl_real_trade_dedup(monkeypatch: pytest.MonkeyPatch) -> None:
    """Enqueue helper blocks duplicate enqueue attempts within TTL."""

    class DummyTask:
        task_id: str = "task-123"

    async def fake_kiq():
        return DummyTask()

    task_fn = cast(Any, crawl_real_trade)
    monkeypatch.setattr(task_fn, "kiq", fake_kiq)

    first = await enqueue_crawl_real_trade(fingerprint="manual-test")
    second = await enqueue_crawl_real_trade(fingerprint="manual-test")

    assert first["enqueued"] is True
    assert first["task_id"] == "task-123"
    assert second == {"enqueued": False, "reason": "duplicate_enqueue"}
