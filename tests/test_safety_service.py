"""Tests for safety service scenarios."""

from decimal import Decimal

import pytest

from src.db.repositories import RealTrade
from src.services.safety_service import SafetyService


@pytest.fixture
def sample_sale_trades():
    """Sample sale trade records for testing."""
    return [
        RealTrade(
            id=1,
            property_type="apt",
            rent_type="sale",
            trade_category="sale",
            region_code="11110",
            dong="사직동",
            apt_name="테스트아파트",
            deposit=50000,
            monthly_rent=0,
            area_m2=Decimal("60.00"),
            floor=10,
            contract_year=2025,
            contract_month=12,
            contract_day=15,
        ),
        RealTrade(
            id=2,
            property_type="apt",
            rent_type="sale",
            trade_category="sale",
            region_code="11110",
            dong="사직동",
            apt_name="테스트아파트2",
            deposit=55000,
            monthly_rent=0,
            area_m2=Decimal("65.00"),
            floor=12,
            contract_year=2025,
            contract_month=11,
            contract_day=20,
        ),
        RealTrade(
            id=3,
            property_type="apt",
            rent_type="sale",
            trade_category="sale",
            region_code="11110",
            dong="사직동",
            apt_name="테스트아파트3",
            deposit=60000,
            monthly_rent=0,
            area_m2=Decimal("55.00"),
            floor=8,
            contract_year=2025,
            contract_month=10,
            contract_day=25,
        ),
    ]


@pytest.mark.anyio
async def test_safety_service_safe_deposit(
    sample_sale_trades: list[RealTrade],
) -> None:
    """SafetyService correctly identifies safe jeonse deposit."""

    session_mock = AsyncMock()
    session_mock.execute.return_value.scalars.return_value.all.return_value = (
        sample_sale_trades
    )

    service = SafetyService(session_mock)
    result = await service.check_jeonse_safety(
        deposit=35000,  # 35만 원 (avg: 50만 원)
        property_type="apt",
        region_code="11110",
        dong="사직동",
        area_m2=Decimal("60.00"),  # Similar area
        period_months=12,
    )

    assert result["status"] == "safe"
    assert result["safety_ratio"] == 0.7
    assert result["avg_sale_price"] == 55000
    assert result["comparable_sales_count"] == 3


@pytest.mark.anyio
async def test_safety_service_caution_deposit(
    sample_sale_trades: list[RealTrade],
) -> None:
    """SafetyService correctly identifies caution-level deposit."""

    session_mock = AsyncMock()
    session_mock.execute.return_value.scalars.return_value.all.return_value = (
        sample_sale_trades
    )

    service = SafetyService(session_mock)
    result = await service.check_jeonse_safety(
        deposit=50000,  # 50만 원 (avg: 55만 원)
        property_type="apt",
        region_code="11110",
        dong="사직동",
        area_m2=Decimal("60.00"),
        period_months=12,
    )

    assert result["status"] == "caution"
    assert 0.9 < result["safety_ratio"] < 1.0


@pytest.mark.anyio
async def test_safety_service_unsafe_deposit(
    sample_sale_trades: list[RealTrade],
) -> None:
    """SafetyService correctly identifies unsafe deposit."""

    session_mock = AsyncMock()
    session_mock.execute.return_value.scalars.return_value.all.return_value = (
        sample_sale_trades
    )

    service = SafetyService(session_mock)
    result = await service.check_jeonse_safety(
        deposit=55000,  # 55만 원 (avg: 55만 원)
        property_type="apt",
        region_code="11110",
        dong="사직동",
        area_m2=Decimal("55.00"),  # Exact match
        period_months=12,
    )

    assert result["status"] == "unsafe"
    assert result["safety_ratio"] == 1.0


@pytest.mark.anyio
async def test_safety_service_no_comparable_sales(
    sample_sale_trades: list[RealTrade],
) -> None:
    """SafetyService returns unknown status when no comparable sales exist."""

    session_mock = AsyncMock()
    session_mock.execute.return_value.scalars.return_value.all.return_value = []

    service = SafetyService(session_mock)
    result = await service.check_jeonse_safety(
        deposit=35000,
        property_type="apt",
        region_code="11110",
        dong="사직동",
        area_m2=Decimal("60.00"),
        period_months=12,
    )

    assert result["status"] == "unknown"
    assert result["comparable_sales_count"] == 0
    assert result["avg_sale_price"] is None


@pytest.mark.anyio
async def test_safety_service_area_filtering(
    sample_sale_trades: list[RealTrade],
) -> None:
    """SafetyService filters by area when specified."""

    session_mock = AsyncMock()

    filtered_trades = [t for t in sample_sale_trades if t.area_m2 == Decimal("60.00")]
    session_mock.execute.return_value.scalars.return_value.all.return_value = (
        filtered_trades
    )

    service = SafetyService(session_mock)
    result = await service.check_jeonse_safety(
        deposit=35000,
        property_type="apt",
        region_code="11110",
        dong="사직동",
        area_m2=Decimal("60.00"),
        period_months=12,
    )

    assert result["comparable_sales_count"] == 1
    assert result["avg_sale_price"] == 50000


@pytest.mark.anyio
async def test_safety_service_period_months() -> None:
    """SafetyService respects custom period_months parameter."""

    session_mock = AsyncMock()
    session_mock.execute.return_value.scalars.return_value.all.return_value = (
        sample_sale_trades
    )

    service = SafetyService(session_mock)
    result = await service.check_jeonse_safety(
        deposit=35000,
        property_type="apt",
        region_code="11110",
        dong="사직동",
        area_m2=Decimal("60.00"),
        period_months=6,  # Last 6 months only
    )

    assert result["comparable_sales_count"] == 3
