"""Business logic for jeonse safety checks."""

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from src.db.repositories import fetch_sale_trades
from src.models.real_trade import RealTrade


class SafetyService:
    """Service for checking jeonse deposit safety against sale prices."""

    SAFE_RATIO_THRESHOLD: float = 0.7
    WARNING_RATIO_THRESHOLD: float = 0.9

    _session: AsyncSession

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _calculate_start_ym(self, period_months: int) -> str:
        """Calculate start year-month string from period months."""
        now = datetime.now(UTC)
        year = now.year
        month = now.month
        for _ in range(max(0, period_months - 1)):
            month -= 1
            if month < 1:
                month = 12
                year -= 1
        return f"{year}{month:02d}"

    async def check_jeonse_safety(
        self,
        deposit: int,
        property_type: str,
        region_code: str | None,
        dong: str | None,
        area_m2: Decimal | None,
        start_year_month: str | None = None,
        end_year_month: str | None = None,
        period_months: int = 12,
    ) -> dict[str, object]:
        """Check if a jeonse deposit is safe compared to sale prices."""

        # Calculate start date range
        if start_year_month and end_year_month:
            sale_trades = await fetch_sale_trades(
                self._session,
                region_code=region_code,
                dong=dong,
                property_type=property_type,
                trade_category="sale",
                start_year_month=start_year_month,
                end_year_month=end_year_month,
            )
        else:
            start_date = self._calculate_start_ym(period_months)
            sale_trades = await fetch_sale_trades(
                self._session,
                region_code=region_code,
                dong=dong,
                property_type=property_type,
                trade_category="sale",
                start_year_month=start_date,
                end_year_month=end_year_month,
            )

        if area_m2 is not None:
            similar_trades = [
                t
                for t in sale_trades
                if t.area_m2 is not None and abs(t.area_m2 - area_m2) <= Decimal("5.0")
            ]
        else:
            similar_trades = sale_trades

        if not similar_trades:
            return {
                "deposit": deposit,
                "status": "unknown",
                "message": "No comparable sale data available",
                "safety_ratio": None,
                "avg_sale_price": None,
                "min_sale_price": None,
                "max_sale_price": None,
                "comparable_sales_count": 0,
            }

        avg_sale = sum(t.deposit for t in similar_trades) / len(similar_trades)
        min_sale = min(t.deposit for t in similar_trades)
        max_sale = max(t.deposit for t in similar_trades)

        safety_ratio = deposit / avg_sale if avg_sale > 0 else 1.0

        if safety_ratio < self.SAFE_RATIO_THRESHOLD:
            status = "safe"
            message = f"Deposit is {safety_ratio * 100:.1f}% of average sale price - within safe range"
        elif safety_ratio < self.WARNING_RATIO_THRESHOLD:
            status = "caution"
            message = f"Deposit is {safety_ratio * 100:.1f}% of average sale price - exercise caution"
        else:
            status = "unsafe"
            message = f"Deposit is {safety_ratio * 100:.1f}% of average sale price - high risk"

        return {
            "deposit": deposit,
            "status": status,
            "message": message,
            "safety_ratio": round(safety_ratio, 4),
            "avg_sale_price": int(avg_sale),
            "min_sale_price": min_sale,
            "max_sale_price": max_sale,
            "comparable_sales_count": len(similar_trades),
        }
