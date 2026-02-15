"""Business logic for listing comparison."""


from sqlalchemy.ext.asyncio import AsyncSession

from src.db.repositories import fetch_listings_by_ids, fetch_market_stats


class ComparisonService:
    """Service layer for MCP comparison tools."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def compare_listings(self, listing_ids: list[int]) -> dict[str, object]:
        """Compare multiple listings side by side."""

        if not listing_ids:
            return {
                "status": "error",
                "message": "No listing IDs provided",
                "comparisons": [],
            }

        if len(listing_ids) < 2:
            return {
                "status": "error",
                "message": "At least 2 listings required for comparison",
                "comparisons": [],
            }

        if len(listing_ids) > 10:
            return {
                "status": "error",
                "message": "Maximum 10 listings can be compared",
                "comparisons": [],
            }

        all_listings = await fetch_listings_by_ids(
            self._session, listing_ids, is_active=True
        )

        listings_map = {lst.id: lst for lst in all_listings}

        found_ids = list(listings_map.keys())
        missing_ids = [lid for lid in listing_ids if lid not in found_ids]

        if missing_ids:
            return {
                "status": "partial",
                "message": f"Some listings not found: {missing_ids}",
                "missing_listing_ids": missing_ids,
                "comparisons": [],
            }

        comparisons = []
        for lst in listings_map.values():
            market = await fetch_market_stats(
                self._session,
                property_type=lst.property_type,
                dong=lst.dong,
                area_m2=lst.area_m2,
            )

            market_avg_deposit = market.avg_deposit if market else None
            market_sample_count = market.sample_count if market else 0
            deposit_vs_market_ratio = None
            if market_avg_deposit and market_avg_deposit > 0:
                deposit_vs_market_ratio = round(lst.deposit / market_avg_deposit, 4)

            comparisons.append(
                {
                    "id": lst.id,
                    "source": lst.source,
                    "property_type": lst.property_type,
                    "rent_type": lst.rent_type,
                    "deposit": lst.deposit,
                    "monthly_rent": lst.monthly_rent,
                    "total_cost": lst.deposit + (lst.monthly_rent * 100),
                    "address": lst.address,
                    "dong": lst.dong,
                    "area_m2": float(lst.area_m2) if lst.area_m2 else None,
                    "floor": lst.floor,
                    "total_floors": lst.total_floors,
                    "price_per_m2": (
                        float(lst.deposit / lst.area_m2)
                        if lst.area_m2 and lst.area_m2 > 0
                        else None
                    ),
                    "market_avg_deposit": int(market_avg_deposit)
                    if market_avg_deposit
                    else None,
                    "deposit_vs_market_ratio": deposit_vs_market_ratio,
                    "market_sample_count": market_sample_count,
                }
            )

        return {
            "status": "success",
            "listing_count": len(comparisons),
            "comparisons": comparisons,
            "summary": self._generate_summary(comparisons),
        }

    def _generate_summary(
        self, comparisons: list[dict[str, object]]
    ) -> dict[str, object]:
        """Generate summary statistics for comparisons."""

        if not comparisons:
            return {}

        deposits: list[int] = [c["deposit"] for c in comparisons]  # type: ignore[assignment]
        monthly_rents: list[int] = [c["monthly_rent"] for c in comparisons]  # type: ignore[assignment]
        areas: list[float] = [
            c["area_m2"] for c in comparisons if c["area_m2"] is not None
        ]  # type: ignore[assignment]
        floors: list[int] = [c["floor"] for c in comparisons if c["floor"] is not None]  # type: ignore[assignment]


        summary = {
            "min_deposit": min(deposits),
            "max_deposit": max(deposits),
            "avg_deposit": int(sum(deposits) / len(deposits)),
            "min_monthly_rent": min(monthly_rents),
            "max_monthly_rent": max(monthly_rents),
            "avg_monthly_rent": int(sum(monthly_rents) / len(monthly_rents)),
        }

        if areas:
            summary["min_area_m2"] = float(min(areas))
            summary["max_area_m2"] = float(max(areas))
            summary["avg_area_m2"] = float(sum(areas) / len(areas))

        if floors:
            summary["min_floor"] = min(floors)
            summary["max_floor"] = max(floors)

        property_types = [c["property_type"] for c in comparisons]
        rent_types = [c["rent_type"] for c in comparisons]

        summary["property_types"] = list(set(property_types))
        summary["rent_types"] = list(set(rent_types))

        return summary
