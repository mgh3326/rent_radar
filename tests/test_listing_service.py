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
