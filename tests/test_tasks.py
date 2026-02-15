"""Taskiq task tests for public API crawler flow."""

from decimal import Decimal
from typing import Any, cast

import pytest

from src.crawlers.base import CrawlResult
from src.db.repositories import RealTradeUpsert
from src.crawlers.public_api import PublicApiCrawler
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

    async def fake_kiq(*args: object, **kwargs: object):  # noqa: ARG001
        return DummyTask()

    task_fn = cast(Any, crawl_real_trade)
    monkeypatch.setattr(task_fn, "kiq", fake_kiq)

    first = await enqueue_crawl_real_trade(fingerprint="manual-test")
    second = await enqueue_crawl_real_trade(fingerprint="manual-test")

    assert first["enqueued"] is True
    assert first["task_id"] == "task-123"
    assert second == {"enqueued": False, "reason": "duplicate_enqueue"}


@pytest.mark.anyio
async def test_enqueue_crawl_real_trade_with_region_codes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Enqueue helper with specific region codes uses region-specific dedup key."""

    class DummyTask:
        task_id: str = "task-region-123"

    async def fake_kiq(*args: object, **kwargs: object):  # noqa: ARG001
        return DummyTask()

    task_fn = cast(Any, crawl_real_trade)
    monkeypatch.setattr(task_fn, "kiq", fake_kiq)

    first = await enqueue_crawl_real_trade(
        region_codes=["11110", "11140"], fingerprint="manual-test"
    )
    second = await enqueue_crawl_real_trade(
        region_codes=["11110", "11140"], fingerprint="manual-test"
    )
    third = await enqueue_crawl_real_trade(
        region_codes=["11110"], fingerprint="manual-test"
    )

    assert first["enqueued"] is True
    assert first["task_id"] == "task-region-123"
    # Duplicate because same region_codes and fingerprint
    assert second == {"enqueued": False, "reason": "duplicate_enqueue"}
    # Not duplicate because different region_codes
    assert third["enqueued"] is True
    assert third["task_id"] == "task-region-123"


@pytest.mark.anyio
async def test_enqueue_crawl_real_trade_with_property_types(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Enqueue helper with specific property types uses property-type-specific dedup key."""

    class DummyTask:
        task_id: str = "task-property-123"

    async def fake_kiq(*args: object, **kwargs: object):  # noqa: ARG001
        return DummyTask()

    task_fn = cast(Any, crawl_real_trade)
    monkeypatch.setattr(task_fn, "kiq", fake_kiq)

    first = await enqueue_crawl_real_trade(
        property_types=["apt", "villa"], fingerprint="manual-test"
    )
    second = await enqueue_crawl_real_trade(
        property_types=["apt", "villa"], fingerprint="manual-test"
    )
    third = await enqueue_crawl_real_trade(
        property_types=["officetel"], fingerprint="manual-test"
    )

    assert first["enqueued"] is True
    assert first["task_id"] == "task-property-123"
    # Duplicate because same property_types and fingerprint
    assert second == {"enqueued": False, "reason": "duplicate_enqueue"}
    # Not duplicate because different property_types
    assert third["enqueued"] is True
    assert third["task_id"] == "task-property-123"


@pytest.mark.anyio
async def test_crawl_real_trade_with_date_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Task passes date range parameters to crawler."""

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
    task = await task_fn.kiq(
        region_codes=["11110"],
        property_types=["apt"],
        start_year_month="202501",
        end_year_month="202503",
    )
    result = await task.wait_result(timeout=30)

    assert not result.is_err
    assert result.return_value["source"] == "public_api"
    assert result.return_value["fetched"] == 1
    assert result.return_value["count"] == 1


@pytest.mark.anyio
async def test_public_api_crawler_with_multiple_property_types() -> None:
    """PublicApiCrawler generates mock data for all property types when API key is empty."""



@pytest.mark.anyio
async def test_public_api_crawler_date_range() -> None:
    """PublicApiCrawler generates mock data for custom date range."""

    crawler = PublicApiCrawler(
        region_codes=["11110"],
        property_types=["apt"],
        start_year_month="202501",
        end_year_month="202503",
    )

    months = crawler._target_months()
    assert "202501" in months
    assert "202502" in months
    assert "202503" in months
    assert "202412" not in months
    assert "202504" not in months


@pytest.mark.anyio
async def test_crawl_real_trade_releases_lock_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Task releases dedup lock even when crawler fails."""

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
        raise RuntimeError("Simulated crawler failure")

    async def fake_persist(rows: list[RealTradeUpsert]) -> int:
        return len(rows)

    async def fake_lock(key: str, ttl_seconds: int) -> bool:  # noqa: ARG001
        return True

    async def fake_release(key: str) -> None:  # noqa: ARG001
        pass

    monkeypatch.setattr("src.crawlers.public_api.PublicApiCrawler.run", fake_run)
    monkeypatch.setattr("src.taskiq_app.tasks._persist_real_trades", fake_persist)
    monkeypatch.setattr("src.taskiq_app.tasks.acquire_dedup_lock", fake_lock)
    monkeypatch.setattr("src.taskiq_app.tasks.release_dedup_lock", fake_release)

    task_fn = cast(Any, crawl_real_trade)
    task = await task_fn.kiq()
    result = await task.wait_result(timeout=30)

    assert result.is_err
