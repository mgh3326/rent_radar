"""Business logic for real trade prices and trends."""

from sqlalchemy.ext.asyncio import AsyncSession

from src.db.repositories import count_real_prices, fetch_price_trend, fetch_real_prices


class PriceService:
    """Service layer for MCP price tools."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_real_price(
        self,
        *,
        region_code: str | None,
        dong: str | None,
        property_type: str,
        period_months: int,
        limit: int = 50,
    ) -> list[dict[str, object]]:
        """Return real trade history rows."""

        rows = await fetch_real_prices(
            self._session,
            region_code=region_code,
            dong=dong,
            property_type=property_type,
            period_months=period_months,
            limit=limit,
        )
        return [
            {
                "id": row.id,
                "region_code": row.region_code,
                "dong": row.dong,
                "apt_name": row.apt_name,
                "property_type": row.property_type,
                "rent_type": row.rent_type,
                "deposit": row.deposit,
                "monthly_rent": row.monthly_rent,
                "area_m2": float(row.area_m2) if row.area_m2 is not None else None,
                "floor": row.floor,
                "contract_year": row.contract_year,
                "contract_month": row.contract_month,
                "contract_day": row.contract_day,
            }
            for row in rows
        ]

    async def get_real_price_with_total_count(
        self,
        *,
        region_code: str | None,
        dong: str | None,
        property_type: str,
        period_months: int,
        limit: int = 50,
    ) -> tuple[list[dict[str, object]], int]:
        rows = await self.get_real_price(
            region_code=region_code,
            dong=dong,
            property_type=property_type,
            period_months=period_months,
            limit=limit,
        )
        returned_count = len(rows)
        if returned_count < limit:
            return rows, returned_count

        total_count = await self.get_real_price_total_count(
            region_code=region_code,
            dong=dong,
            property_type=property_type,
            period_months=period_months,
        )
        return rows, total_count

    async def get_real_price_total_count(
        self,
        *,
        region_code: str | None,
        dong: str | None,
        property_type: str,
        period_months: int,
    ) -> int:
        return await count_real_prices(
            self._session,
            region_code=region_code,
            dong=dong,
            property_type=property_type,
            period_months=period_months,
        )

    async def get_price_trend(
        self,
        *,
        region_code: str | None,
        dong: str | None,
        property_type: str,
        period_months: int,
    ) -> list[dict[str, object]]:
        """Return monthly average trend rows."""

        rows = await fetch_price_trend(
            self._session,
            region_code=region_code,
            dong=dong,
            property_type=property_type,
            period_months=period_months,
        )
        return [
            {
                "contract_year": row.contract_year,
                "contract_month": row.contract_month,
                "avg_deposit": row.avg_deposit,
                "avg_monthly_rent": row.avg_monthly_rent,
                "trade_count": row.trade_count,
            }
            for row in rows
        ]
