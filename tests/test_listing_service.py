"""Tests for listing service filtering and search."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.repositories import fetch_listings
from src.services.listing_service import ListingService


def _mock_session_for_listings() -> AsyncMock:
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    session = AsyncMock()
    session.execute.return_value = mock_result
    return session


@pytest.mark.anyio
async def test_fetch_listings_filters_by_region() -> None:
    session = _mock_session_for_listings()
    await fetch_listings(
        session,
        region_code="11110",
        dong="종로구",
        source="naver",
    )
    assert session.execute.called


@pytest.mark.anyio
async def test_fetch_listings_region_code_maps_to_hybrid_address_and_dong_filter() -> (
    None
):
    session = _mock_session_for_listings()

    await fetch_listings(
        session,
        region_code="41135",
    )

    stmt = session.execute.call_args.args[0]
    criteria = [str(item) for item in stmt._where_criteria]

    assert any("lower(listings.address) LIKE lower" in item for item in criteria)
    assert any("listings.dong IN" in item for item in criteria)


@pytest.mark.anyio
async def test_fetch_listings_region_code_and_dong_filters_are_combined() -> None:
    session = _mock_session_for_listings()

    await fetch_listings(
        session,
        region_code="41135",
        dong="분당구",
    )

    stmt = session.execute.call_args.args[0]
    criteria = [str(item) for item in stmt._where_criteria]

    assert any("listings.dong IN" in item for item in criteria)
    assert any("lower(listings.dong) LIKE lower" in item for item in criteria)


@pytest.mark.anyio
async def test_fetch_listings_region_code_for_ambiguous_sigungu_includes_sido_address() -> (
    None
):
    session = _mock_session_for_listings()

    await fetch_listings(
        session,
        region_code="11140",
    )

    stmt = session.execute.call_args.args[0]
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))

    assert "%서울특별시%" in compiled
    assert "%중구%" in compiled


@pytest.mark.anyio
async def test_fetch_listings_region_code_matches_sigungu_even_with_address_whitespace() -> (
    None
):
    session = _mock_session_for_listings()

    await fetch_listings(
        session,
        region_code="41135",
    )

    stmt = session.execute.call_args.args[0]
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))

    assert "replace(listings.address, ' ', '')" in compiled
    assert "%성남시분당구%" in compiled


@pytest.mark.anyio
async def test_fetch_listings_invalid_region_code_returns_empty_without_query() -> None:
    session = _mock_session_for_listings()

    result = await fetch_listings(
        session,
        region_code="99999",
    )

    assert result == []
    session.execute.assert_not_called()


@pytest.mark.anyio
async def test_fetch_listings_filters_by_property_type() -> None:
    session = _mock_session_for_listings()
    await fetch_listings(
        session,
        property_type="apt",
        source="naver",
    )
    assert session.execute.called


@pytest.mark.anyio
async def test_fetch_listings_filters_by_rent_type() -> None:
    session = _mock_session_for_listings()
    await fetch_listings(
        session,
        rent_type="jeonse",
        source="naver",
    )
    assert session.execute.called


@pytest.mark.anyio
async def test_fetch_listings_filters_by_price_range() -> None:
    session = _mock_session_for_listings()
    await fetch_listings(
        session,
        min_deposit=30000,
        max_deposit=50000,
        source="naver",
    )
    assert session.execute.called


@pytest.mark.anyio
async def test_fetch_listings_active_only() -> None:
    session = _mock_session_for_listings()
    await fetch_listings(
        session,
        is_active=True,
        source="naver",
    )
    assert session.execute.called


@dataclass(slots=True)
class _FreshnessSnapshot:
    total_count: int
    last_seen_at: datetime | None


@pytest.mark.anyio
async def test_evaluate_crawl_status_no_region_filter() -> None:
    service = ListingService(cast(AsyncSession, object()))

    status = await service.evaluate_crawl_status(region_code="   ")

    assert status == {
        "source": "zigbang",
        "region_code": None,
        "evaluated": False,
        "needs_crawl": None,
        "reason": "no_region_filter",
        "last_seen_at": None,
        "stale_threshold_hours": 48,
    }


@pytest.mark.anyio
async def test_evaluate_crawl_status_invalid_region_code() -> None:
    service = ListingService(cast(AsyncSession, object()))

    status = await service.evaluate_crawl_status(region_code="99999")

    assert status == {
        "source": "zigbang",
        "region_code": "99999",
        "evaluated": False,
        "needs_crawl": None,
        "reason": "invalid_region_code",
        "last_seen_at": None,
        "stale_threshold_hours": 48,
    }


@pytest.mark.anyio
async def test_evaluate_crawl_status_no_region_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_fetch_listing_region_source_freshness(
        _session: AsyncSession,
        *,
        region_code: str,
        source: str,
    ) -> _FreshnessSnapshot:
        assert region_code == "11110"
        assert source == "zigbang"
        return _FreshnessSnapshot(total_count=0, last_seen_at=None)

    monkeypatch.setattr(
        "src.services.listing_service.fetch_listing_region_source_freshness",
        fake_fetch_listing_region_source_freshness,
        raising=False,
    )

    service = ListingService(cast(AsyncSession, object()))
    status = await service.evaluate_crawl_status(region_code="11110")

    assert status == {
        "source": "zigbang",
        "region_code": "11110",
        "evaluated": True,
        "needs_crawl": True,
        "reason": "no_region_data",
        "last_seen_at": None,
        "stale_threshold_hours": 48,
    }


@pytest.mark.anyio
async def test_evaluate_crawl_status_stale_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stale_seen_at = datetime.now(UTC) - timedelta(hours=49)

    async def fake_fetch_listing_region_source_freshness(
        _session: AsyncSession,
        *,
        region_code: str,
        source: str,
    ) -> _FreshnessSnapshot:
        assert region_code == "11110"
        assert source == "zigbang"
        return _FreshnessSnapshot(total_count=12, last_seen_at=stale_seen_at)

    monkeypatch.setattr(
        "src.services.listing_service.fetch_listing_region_source_freshness",
        fake_fetch_listing_region_source_freshness,
        raising=False,
    )

    service = ListingService(cast(AsyncSession, object()))
    status = await service.evaluate_crawl_status(region_code="11110")

    assert status == {
        "source": "zigbang",
        "region_code": "11110",
        "evaluated": True,
        "needs_crawl": True,
        "reason": "stale_data",
        "last_seen_at": stale_seen_at.isoformat(),
        "stale_threshold_hours": 48,
    }


@pytest.mark.anyio
async def test_evaluate_crawl_status_fresh_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fresh_seen_at = datetime.now(UTC) - timedelta(hours=24)

    async def fake_fetch_listing_region_source_freshness(
        _session: AsyncSession,
        *,
        region_code: str,
        source: str,
    ) -> _FreshnessSnapshot:
        assert region_code == "11110"
        assert source == "zigbang"
        return _FreshnessSnapshot(total_count=7, last_seen_at=fresh_seen_at)

    monkeypatch.setattr(
        "src.services.listing_service.fetch_listing_region_source_freshness",
        fake_fetch_listing_region_source_freshness,
        raising=False,
    )

    service = ListingService(cast(AsyncSession, object()))
    status = await service.evaluate_crawl_status(region_code="11110")

    assert status == {
        "source": "zigbang",
        "region_code": "11110",
        "evaluated": True,
        "needs_crawl": False,
        "reason": "fresh_data",
        "last_seen_at": fresh_seen_at.isoformat(),
        "stale_threshold_hours": 48,
    }


@pytest.mark.anyio
async def test_evaluate_crawl_status_uses_default_stale_threshold_and_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_region_codes: list[str] = []
    captured_sources: list[str] = []

    async def fake_fetch_listing_region_source_freshness(
        _session: AsyncSession,
        *,
        region_code: str,
        source: str,
    ) -> _FreshnessSnapshot:
        captured_region_codes.append(region_code)
        captured_sources.append(source)
        return _FreshnessSnapshot(total_count=0, last_seen_at=None)

    monkeypatch.setattr(
        "src.services.listing_service.fetch_listing_region_source_freshness",
        fake_fetch_listing_region_source_freshness,
        raising=False,
    )

    service = ListingService(cast(AsyncSession, object()))
    status = await service.evaluate_crawl_status(region_code="11110")

    assert captured_region_codes == ["11110"]
    assert captured_sources == ["zigbang"]
    assert status["stale_threshold_hours"] == 48


@pytest.mark.anyio
async def test_search_listings_normalizes_region_code_before_repository_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_region_codes: list[str | None] = []

    async def fake_fetch_listings(
        _session: AsyncSession,
        **kwargs: object,
    ) -> list[object]:
        captured_region_codes.append(cast(str | None, kwargs.get("region_code")))
        return []

    monkeypatch.setattr(
        "src.services.listing_service.fetch_listings",
        fake_fetch_listings,
    )

    service = ListingService(cast(AsyncSession, object()))
    results = await service.search_listings(region_code=" 11110 ")

    assert results == []
    assert captured_region_codes == ["11110"]


@pytest.mark.anyio
async def test_evaluate_crawl_status_converts_naive_last_seen_at_to_utc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    naive_seen_at = datetime.now() - timedelta(hours=80)

    async def fake_fetch_listing_region_source_freshness(
        _session: AsyncSession,
        *,
        region_code: str,
        source: str,
    ) -> _FreshnessSnapshot:
        assert region_code == "11110"
        assert source == "zigbang"
        return _FreshnessSnapshot(total_count=1, last_seen_at=naive_seen_at)

    monkeypatch.setattr(
        "src.services.listing_service.fetch_listing_region_source_freshness",
        fake_fetch_listing_region_source_freshness,
        raising=False,
    )

    service = ListingService(cast(AsyncSession, object()))
    status = await service.evaluate_crawl_status(region_code="11110")

    assert status["needs_crawl"] is True
    assert status["reason"] == "stale_data"
    assert isinstance(status["last_seen_at"], str)
    assert cast(str, status["last_seen_at"]).endswith("+00:00")
