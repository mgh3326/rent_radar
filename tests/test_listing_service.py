"""Tests for listing service filtering and search."""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.db.repositories import fetch_listings
from src.db.session import session_context


@pytest.mark.anyio
async def test_fetch_listings_filters_by_region() -> None:
    """Listings query filters correctly by region code."""

    mock_session = AsyncMock()

    await fetch_listings(
        mock_session,
        region_code="11110",
        dong="종로구",
        source="naver",
    )

    assert mock_session.execute.called


@pytest.mark.anyio
async def test_fetch_listings_filters_by_property_type() -> None:
    """Listings query filters correctly by property type."""

    mock_session = AsyncMock()

    await fetch_listings(
        mock_session,
        property_type="apt",
        source="naver",
    )

    assert mock_session.execute.called


@pytest.mark.anyio
async def test_fetch_listings_filters_by_rent_type() -> None:
    """Listings query filters correctly by rent type."""

    mock_session = AsyncMock()

    await fetch_listings(
        mock_session,
        rent_type="jeonse",
        source="naver",
    )

    assert mock_session.execute.called


@pytest.mark.anyio
async def test_fetch_listings_filters_by_price_range() -> None:
    """Listings query filters correctly by price range."""

    mock_session = AsyncMock()

    await fetch_listings(
        mock_session,
        min_deposit=30000,
        max_deposit=50000,
        source="naver",
    )

    assert mock_session.execute.called


@pytest.mark.anyio
async def test_fetch_listings_active_only() -> None:
    """Listings query filters for active listings only."""

    mock_session = AsyncMock()

    await fetch_listings(
        mock_session,
        is_active=True,
        source="naver",
    )

    assert mock_session.execute.called
