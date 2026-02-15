"""Tests for listing service filtering and search."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.db.repositories import fetch_listings


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
