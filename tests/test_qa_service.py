from datetime import UTC, datetime, timedelta
from decimal import Decimal
from collections.abc import Iterator
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.repositories import (
    CrawlSourceSnapshot,
    DataQualityIssue,
    fetch_data_quality_issues,
)
from src.models.listing import Listing
from src.models.real_trade import RealTrade
from src.services.qa_service import QAService


class _FakeExecuteResult:
    def __init__(
        self,
        *,
        scalar_value: object | None = None,
        scalar_rows: list[object] | None = None,
    ) -> None:
        self._scalar_value: object | None = scalar_value
        self._scalar_rows: list[object] = scalar_rows or []

    def scalar_one_or_none(self) -> object | None:
        return self._scalar_value

    def scalars(self) -> "_FakeExecuteResult":
        return self

    def all(self) -> list[object]:
        return self._scalar_rows


class _FakeSession:
    def __init__(self, results: list[_FakeExecuteResult]) -> None:
        self._results: Iterator[_FakeExecuteResult] = iter(results)

    async def execute(self, _stmt: object) -> _FakeExecuteResult:
        return next(self._results)


@pytest.mark.anyio
async def test_fetch_data_quality_issues_detects_expected_rules() -> None:
    now = datetime.now(UTC)
    future = now + timedelta(days=2)

    blocker_future = RealTrade(
        id=1001,
        property_type="apt",
        rent_type="jeonse",
        region_code="11110",
        dong="사직동",
        apt_name="미래아파트",
        deposit=22000,
        monthly_rent=0,
        area_m2=Decimal("84.90"),
        floor=10,
        contract_year=future.year,
        contract_month=future.month,
        contract_day=future.day,
    )
    warning_area = RealTrade(
        id=1002,
        property_type="apt",
        rent_type="monthly",
        region_code="11110",
        dong="세종로",
        apt_name="소형아파트",
        deposit=5000,
        monthly_rent=50,
        area_m2=Decimal("9.50"),
        floor=4,
        contract_year=now.year,
        contract_month=now.month,
        contract_day=max(1, now.day - 1),
    )
    warning_stale = Listing(
        id=2001,
        source="naver",
        source_id="N-2001",
        property_type="apt",
        rent_type="jeonse",
        deposit=30000,
        monthly_rent=0,
        address="서울 종로구 사직동",
        dong="사직동",
        detail_address=None,
        area_m2=Decimal("59.95"),
        floor=7,
        total_floors=20,
        description=None,
        latitude=None,
        longitude=None,
        is_active=True,
        last_seen_at=now - timedelta(days=8),
        first_seen_at=now - timedelta(days=10),
    )

    session = _FakeSession(
        [
            _FakeExecuteResult(scalar_rows=[blocker_future]),
            _FakeExecuteResult(scalar_rows=[warning_area]),
            _FakeExecuteResult(scalar_rows=[warning_stale]),
        ]
    )

    issues = await fetch_data_quality_issues(
        cast(AsyncSession, cast(object, session)),
        limit=100,
    )

    assert any(
        issue.id == 1001
        and issue.table_name == "real_trades"
        and issue.severity == "blocker"
        and "future_contract_date" in issue.issue_type
        for issue in issues
    )
    assert any(
        issue.id == 1002
        and issue.table_name == "real_trades"
        and issue.severity == "warning"
        and "area_m2=" in issue.issue_type
        for issue in issues
    )
    assert any(
        issue.id == 2001
        and issue.table_name == "listings"
        and issue.severity == "warning"
        and "stale_active_listing" in issue.issue_type
        for issue in issues
    )


@pytest.mark.anyio
async def test_qa_service_summary_counts_and_deployment_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(UTC)

    async def fake_snapshots(
        _session: AsyncSession, lookback_hours: int = 24
    ) -> list[CrawlSourceSnapshot]:
        assert lookback_hours == 24
        return [
            CrawlSourceSnapshot(
                source="public_api",
                table_name="real_trades",
                total_count=50,
                last_24h_count=7,
                last_updated=now,
            )
        ]

    async def fake_issues(
        _session: AsyncSession, limit: int = 100
    ) -> list[DataQualityIssue]:
        assert limit == 100
        return [
            DataQualityIssue(
                id=1,
                table_name="real_trades",
                issue_type="deposit<=0",
                severity="blocker",
                description="blocking issue",
                record_data={"deposit": 0},
            ),
            DataQualityIssue(
                id=2,
                table_name="listings",
                issue_type="stale_active_listing",
                severity="warning",
                description="warning issue",
                record_data={"is_active": True},
            ),
        ]

    monkeypatch.setattr("src.services.qa_service.fetch_crawl_snapshots", fake_snapshots)
    monkeypatch.setattr(
        "src.services.qa_service.fetch_data_quality_issues", fake_issues
    )

    service = QAService(cast(AsyncSession, object()))
    summary = await service.get_qa_summary()
    snapshots = cast(list[dict[str, object]], summary["snapshots"])

    assert summary["blocker_count"] == 1
    assert summary["warning_count"] == 1
    assert summary["total_issues"] == 2
    assert summary["deployment_ready"] is False
    assert snapshots[0]["last_updated"] == now.isoformat()


@pytest.mark.anyio
async def test_qa_service_passes_custom_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_lookback: list[int] = []
    captured_limit: list[int] = []

    async def fake_snapshots(
        _session: AsyncSession, lookback_hours: int = 24
    ) -> list[CrawlSourceSnapshot]:
        captured_lookback.append(lookback_hours)
        return []

    async def fake_issues(
        _session: AsyncSession, limit: int = 100
    ) -> list[DataQualityIssue]:
        captured_limit.append(limit)
        return []

    monkeypatch.setattr("src.services.qa_service.fetch_crawl_snapshots", fake_snapshots)
    monkeypatch.setattr(
        "src.services.qa_service.fetch_data_quality_issues", fake_issues
    )

    service = QAService(cast(AsyncSession, object()))
    _ = await service.get_snapshots(lookback_hours=48)
    _ = await service.get_issues(limit=20)

    assert captured_lookback == [48]
    assert captured_limit == [20]
