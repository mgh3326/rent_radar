"""Service-level tests used by MCP price tools."""

from decimal import Decimal
from typing import Any, cast

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

    captured_kwargs: dict[str, object] = {}

    async def fake_fetch_real_prices(*args: object, **kwargs: object):  # noqa: ARG001
        captured_kwargs.update(kwargs)
        return [sample_row]

    monkeypatch.setattr(
        "src.services.price_service.fetch_real_prices", fake_fetch_real_prices
    )

    service = PriceService(cast(AsyncSession, object()))
    rows = await service.get_real_price(
        region_code="11140", dong="아현동", property_type="apt", period_months=6
    )

    assert len(rows) == 1
    assert rows[0]["apt_name"] == "테스트아파트"
    assert rows[0]["deposit"] == 35000
    assert rows[0]["area_m2"] == 84.12
    assert captured_kwargs["limit"] == 50


@pytest.mark.anyio
async def test_price_service_get_real_price_passes_explicit_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_kwargs: dict[str, object] = {}

    async def fake_fetch_real_prices(*args: object, **kwargs: object):  # noqa: ARG001
        captured_kwargs.update(kwargs)
        return []

    monkeypatch.setattr(
        "src.services.price_service.fetch_real_prices", fake_fetch_real_prices
    )

    service = PriceService(cast(AsyncSession, object()))
    rows = await service.get_real_price(
        region_code="11140",
        dong="아현동",
        property_type="apt",
        period_months=6,
        limit=20,
    )

    assert rows == []
    assert captured_kwargs["limit"] == 20


@pytest.mark.anyio
async def test_price_service_get_real_price_total_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_kwargs: dict[str, object] = {}

    async def fake_count_real_prices(*args: object, **kwargs: object) -> int:  # noqa: ARG001
        captured_kwargs.update(kwargs)
        return 77

    monkeypatch.setattr(
        "src.services.price_service.count_real_prices", fake_count_real_prices
    )

    service = PriceService(cast(AsyncSession, object()))
    total_count = await service.get_real_price_total_count(
        region_code="11140",
        dong="아현동",
        property_type="apt",
        period_months=6,
    )

    assert total_count == 77
    assert captured_kwargs["region_code"] == "11140"
    assert captured_kwargs["dong"] == "아현동"
    assert captured_kwargs["property_type"] == "apt"
    assert captured_kwargs["period_months"] == 6


@pytest.mark.anyio
async def test_price_service_get_real_price_with_total_count_skips_count_when_under_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_rows_kwargs: dict[str, object] = {}
    captured_count_kwargs: dict[str, object] = {}
    count_call_count = 0

    async def fake_get_real_price(self: Any, **kwargs: Any) -> list[dict[str, object]]:  # noqa: ARG001
        captured_rows_kwargs.update(kwargs)
        return [{"id": 1}, {"id": 2}]

    async def fake_get_real_price_total_count(self: Any, **kwargs: Any) -> int:  # noqa: ARG001
        nonlocal count_call_count
        count_call_count += 1
        captured_count_kwargs.update(kwargs)
        return 999

    monkeypatch.setattr(PriceService, "get_real_price", fake_get_real_price)
    monkeypatch.setattr(
        PriceService,
        "get_real_price_total_count",
        fake_get_real_price_total_count,
    )

    service = PriceService(cast(AsyncSession, object()))
    rows, total_count = await service.get_real_price_with_total_count(
        region_code="11140",
        dong="아현동",
        property_type="apt",
        period_months=6,
        limit=50,
    )

    assert rows == [{"id": 1}, {"id": 2}]
    assert total_count == 2
    assert captured_rows_kwargs["limit"] == 50
    assert count_call_count == 0
    assert captured_count_kwargs == {}


@pytest.mark.anyio
async def test_price_service_get_real_price_with_total_count_calls_count_at_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_rows_kwargs: dict[str, object] = {}
    captured_count_kwargs: dict[str, object] = {}
    count_call_count = 0

    async def fake_get_real_price(self: Any, **kwargs: Any) -> list[dict[str, object]]:  # noqa: ARG001
        captured_rows_kwargs.update(kwargs)
        return [{"id": index} for index in range(20)]

    async def fake_get_real_price_total_count(self: Any, **kwargs: Any) -> int:  # noqa: ARG001
        nonlocal count_call_count
        count_call_count += 1
        captured_count_kwargs.update(kwargs)
        return 85

    monkeypatch.setattr(PriceService, "get_real_price", fake_get_real_price)
    monkeypatch.setattr(
        PriceService,
        "get_real_price_total_count",
        fake_get_real_price_total_count,
    )

    service = PriceService(cast(AsyncSession, object()))
    rows, total_count = await service.get_real_price_with_total_count(
        region_code="11140",
        dong="아현동",
        property_type="apt",
        period_months=6,
        limit=20,
    )

    assert len(rows) == 20
    assert total_count == 85
    assert captured_rows_kwargs["limit"] == 20
    assert count_call_count == 1
    assert captured_count_kwargs["region_code"] == "11140"
    assert captured_count_kwargs["dong"] == "아현동"
    assert captured_count_kwargs["property_type"] == "apt"
    assert captured_count_kwargs["period_months"] == 6


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
        region_code="11140", dong=None, property_type="apt", period_months=12
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


@pytest.mark.anyio
async def test_price_service_get_real_price_with_villa(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PriceService filters by property_type (villa)."""

    sample_row = RealTrade(
        id=1,
        property_type="villa",
        rent_type="jeonse",
        region_code="11110",
        dong="아현동",
        apt_name="테스트연립",
        deposit=25000,
        monthly_rent=0,
        area_m2=Decimal("64.5"),
        floor=4,
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
        region_code="11140", dong="아현동", property_type="villa", period_months=6
    )

    assert len(rows) == 1
    assert rows[0]["property_type"] == "villa"
    assert rows[0]["apt_name"] == "테스트연립"
    assert rows[0]["deposit"] == 25000
