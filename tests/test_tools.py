"""Service-level tests used by MCP price tools."""

from decimal import Decimal
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.repositories import PriceTrendPoint
from src.models.real_trade import RealTrade
from src.services.price_service import PriceService


@pytest.mark.anyio
async def test_price_service_get_real_price(monkeypatch: pytest.MonkeyPatch) -> None:
    """PriceService maps real trade rows to tool response schema."""

    sample_row = RealTrade(
        id=1,
        property_type="apt",
        rent_type="jeonse",
        region_code="11110",
        dong="아현동",
        apt_name="테스트아파트",
        deposit=35000,
        monthly_rent=0,
        area_m2=Decimal("84.12"),
        floor=12,
        contract_year=2026,
        contract_month=1,
        contract_day=5,
    )

    async def fake_fetch_real_prices(*args: object, **kwargs: object):  # noqa: ARG001
        return [sample_row]

    monkeypatch.setattr(
        "src.services.price_service.fetch_real_prices", fake_fetch_real_prices
    )

    service = PriceService(cast(AsyncSession, object()))
    rows = await service.get_real_price(
        region="마포구", dong="아현동", property_type="apt", period_months=6
    )

    assert len(rows) == 1
    assert rows[0]["apt_name"] == "테스트아파트"
    assert rows[0]["deposit"] == 35000
    assert rows[0]["area_m2"] == 84.12


@pytest.mark.anyio
async def test_price_service_get_price_trend(monkeypatch: pytest.MonkeyPatch) -> None:
    """PriceService maps trend rows to response schema."""

    async def fake_fetch_price_trend(*args: object, **kwargs: object):  # noqa: ARG001
        return [
            PriceTrendPoint(
                contract_year=2025,
                contract_month=12,
                avg_deposit=30000.0,
                avg_monthly_rent=45.0,
                trade_count=14,
            )
        ]

    monkeypatch.setattr(
        "src.services.price_service.fetch_price_trend", fake_fetch_price_trend
    )

    service = PriceService(cast(AsyncSession, object()))
    trend = await service.get_price_trend(
        region="마포구", dong=None, property_type="apt", period_months=12
    )

    assert trend == [
        {
            "contract_year": 2025,
            "contract_month": 12,
            "avg_deposit": 30000.0,
            "avg_monthly_rent": 45.0,
            "trade_count": 14,
        }
    ]
