"""Business logic for listing recommendations."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast

from sqlalchemy.ext.asyncio import AsyncSession

from src.config.region_codes import is_valid_region_code
from src.db.repositories import (
    BaselineComparisonStats,
    fetch_baseline_comparison_stats,
    fetch_listings,
)


class RecommendationService:
    """Service layer for listing recommendations."""

    DEPOSIT_MONTHLY_EQUIV_RATE = Decimal("0.005")  # 보증금 월세 환산율
    RENT_TYPE_ALIASES = {
        "monthly": "monthly",
        "jeonse": "jeonse",
        "월세": "monthly",
        "전세": "jeonse",
    }

    def __init__(self, session: AsyncSession) -> None:
        self._session: AsyncSession = session

    def _calculate_total_monthly_cost(self, deposit: int, monthly_rent: int) -> Decimal:
        """Calculate total monthly cost including deposit equivalent.

        Formula: total_monthly_cost = monthly_rent + (deposit * 0.005)
        """
        return Decimal(monthly_rent) + (
            Decimal(deposit) * self.DEPOSIT_MONTHLY_EQUIV_RATE
        )

    def _calculate_monthly_cost_per_m2(
        self, total_monthly_cost: Decimal, area_m2: Decimal
    ) -> Decimal:
        """Calculate monthly cost per square meter.

        Formula: monthly_cost_per_m2 = total_monthly_cost / area_m2
        """
        if area_m2 is None or area_m2 <= 0:
            return Decimal("0")
        return total_monthly_cost / area_m2

    def _calculate_deal_delta_pct(
        self, baseline_monthly_cost_per_m2: float, monthly_cost_per_m2: Decimal
    ) -> float:
        """Calculate deal delta percentage.

        Formula: ((baseline - actual) / baseline) * 100
        Positive = cheaper than baseline, Negative = more expensive
        """
        if baseline_monthly_cost_per_m2 is None or baseline_monthly_cost_per_m2 == 0:
            return 0.0
        baseline = Decimal(str(baseline_monthly_cost_per_m2))
        delta = ((baseline - monthly_cost_per_m2) / baseline) * Decimal("100")
        return float(delta)

    def _calculate_recommendation_score(self, deal_delta_pct: float) -> int:
        """Calculate recommendation score.

        Formula: clamp(50 + deal_delta_pct * 2, 0, 100)
        """
        score = 50 + int(deal_delta_pct * 2)
        return max(0, min(100, score))

    def _build_recommendation_reasons(
        self,
        *,
        deal_delta_pct: float,
        total_monthly_cost: Decimal,
        monthly_cost_per_m2: Decimal,
        baseline: BaselineComparisonStats,
    ) -> list[str]:
        """Build human-readable recommendation reasons."""
        reasons = []

        # Reason 1: Price comparison vs baseline
        if deal_delta_pct > 5:
            reasons.append(f"시세 대비 {deal_delta_pct:.1f}% 저렴함")
        elif deal_delta_pct < -5:
            reasons.append(f"시세 대비 {abs(deal_delta_pct):.1f}% 비쌈")
        else:
            reasons.append(f"시세 대비 {deal_delta_pct:+.1f}% 차이")

        # Reason 2: Cost breakdown
        reasons.append(
            f"환산월세 {int(total_monthly_cost):,}원, ㎡당 {float(monthly_cost_per_m2):,.0f}원"
        )

        # Reason 3: Baseline scope and sample count
        scope_desc = {
            "dong": "동일 동",
            "region": "동일 지역",
            "fallback": "전체 지역",
        }
        scope_text = scope_desc.get(baseline.scope, baseline.scope)
        reasons.append(f"비교군: {scope_text}, 표본 {baseline.sample_count}건")

        return reasons

    def _normalize_rent_type(self, rent_type: str | None) -> str | None:
        if rent_type is None:
            return None

        normalized = rent_type.strip()
        if not normalized:
            return None

        lowered = normalized.lower()
        if lowered in self.RENT_TYPE_ALIASES:
            return self.RENT_TYPE_ALIASES[lowered]

        return self.RENT_TYPE_ALIASES.get(normalized, normalized)

    async def evaluate_crawl_status(
        self,
        *,
        region_code: str | None,
        stale_hours: int = 48,
        source: str = "zigbang",
    ) -> dict[str, object]:
        """Evaluate if crawl is needed for the given region.

        Reuses ListingService.evaluate_crawl_status pattern.
        """
        normalized_region_code = region_code.strip() if region_code else ""
        if not normalized_region_code:
            return {
                "source": source,
                "region_code": None,
                "evaluated": False,
                "needs_crawl": None,
                "reason": "no_region_filter",
                "last_seen_at": None,
                "stale_threshold_hours": stale_hours,
            }

        if not is_valid_region_code(normalized_region_code):
            return {
                "source": source,
                "region_code": normalized_region_code,
                "evaluated": False,
                "needs_crawl": None,
                "reason": "invalid_region_code",
                "last_seen_at": None,
                "stale_threshold_hours": stale_hours,
            }

        from src.db.repositories import fetch_listing_region_source_freshness

        freshness = await fetch_listing_region_source_freshness(
            self._session,
            region_code=normalized_region_code,
            source=source,
        )

        if freshness.total_count == 0:
            return {
                "source": source,
                "region_code": normalized_region_code,
                "evaluated": True,
                "needs_crawl": True,
                "reason": "no_region_data",
                "last_seen_at": None,
                "stale_threshold_hours": stale_hours,
            }

        if freshness.last_seen_at is None:
            return {
                "source": source,
                "region_code": normalized_region_code,
                "evaluated": True,
                "needs_crawl": True,
                "reason": "stale_data",
                "last_seen_at": None,
                "stale_threshold_hours": stale_hours,
            }

        last_seen_at = freshness.last_seen_at
        if last_seen_at.tzinfo is None:
            last_seen_at = last_seen_at.replace(tzinfo=UTC)

        stale_threshold = datetime.now(UTC) - timedelta(hours=stale_hours)
        needs_crawl = last_seen_at < stale_threshold

        return {
            "source": source,
            "region_code": normalized_region_code,
            "evaluated": True,
            "needs_crawl": needs_crawl,
            "reason": "stale_data" if needs_crawl else "fresh_data",
            "last_seen_at": last_seen_at.isoformat(),
            "stale_threshold_hours": stale_hours,
        }

    async def recommend_listings(
        self,
        *,
        region_code: str,
        dong: str | None = None,
        property_types: list[str] | None = None,
        rent_type: str | None = None,
        min_deposit: int | None = None,
        max_deposit: int | None = None,
        min_monthly_rent: int | None = None,
        max_monthly_rent: int | None = None,
        min_area: Decimal | None = None,
        max_area: Decimal | None = None,
        min_floor: int | None = None,
        max_floor: int | None = None,
        limit: int = 10,
        source: str = "zigbang",
    ) -> dict[str, object]:
        """Recommend listings based on price comparison to baseline.

        Returns listings ranked by recommendation_score, which reflects
        how much cheaper/more expensive the listing is compared to the
        baseline for the same property type and area range.
        """
        # Default property types for villa/officetel recommendations
        if property_types is None:
            property_types = ["villa", "officetel"]

        normalized_region_code = region_code.strip() if region_code else ""
        normalized_rent_type = self._normalize_rent_type(rent_type)

        base_query = {
            "region_code": normalized_region_code or None,
            "dong": dong,
            "property_types": property_types,
            "rent_type": normalized_rent_type,
            "min_deposit": min_deposit,
            "max_deposit": max_deposit,
            "min_monthly_rent": min_monthly_rent,
            "max_monthly_rent": max_monthly_rent,
            "min_area": float(min_area) if min_area else None,
            "max_area": float(max_area) if max_area else None,
            "min_floor": min_floor,
            "max_floor": max_floor,
            "limit": limit,
            "source": source,
        }

        if not normalized_region_code:
            return {
                "status": "error",
                "query": base_query,
                "count": 0,
                "items": [],
                "message": "region_code is required",
            }

        if not is_valid_region_code(normalized_region_code):
            return {
                "status": "error",
                "query": base_query,
                "count": 0,
                "items": [],
                "message": "region_code must be a valid supported region code",
            }

        # Step 1: Evaluate crawl status first
        crawl_status = await self.evaluate_crawl_status(
            region_code=normalized_region_code,
            source=source,
        )

        if crawl_status.get("needs_crawl") is True:
            return {
                "status": "needs_crawl",
                "query": base_query,
                "count": 0,
                "items": [],
                "crawl_status": crawl_status,
                "crawl_message": "해당 지역의 데이터가 없거나 오래되어 크롤링이 필요합니다.",
            }

        # Step 2: Fetch candidate listings
        all_candidates = []
        for prop_type in property_types:
            rows = await fetch_listings(
                self._session,
                region_code=normalized_region_code,
                dong=dong,
                property_type=prop_type,
                rent_type=normalized_rent_type,
                min_deposit=min_deposit,
                max_deposit=max_deposit,
                min_monthly_rent=min_monthly_rent,
                max_monthly_rent=max_monthly_rent,
                min_area=min_area,
                max_area=max_area,
                min_floor=min_floor,
                max_floor=max_floor,
                is_active=True,
                source=source,
                limit=500,  # Fetch more for scoring
            )
            all_candidates.extend(rows)

        # Step 3: Filter out listings without valid area_m2
        valid_candidates = [
            row for row in all_candidates if row.area_m2 is not None and row.area_m2 > 0
        ]

        # Step 4: Score each listing
        scored_items = []
        for listing in valid_candidates:
            # Calculate listing's metrics
            total_monthly_cost = self._calculate_total_monthly_cost(
                listing.deposit, listing.monthly_rent
            )
            monthly_cost_per_m2 = self._calculate_monthly_cost_per_m2(
                total_monthly_cost, listing.area_m2
            )

            # Fetch baseline for comparison
            baseline = await fetch_baseline_comparison_stats(
                self._session,
                property_type=listing.property_type,
                dong=listing.dong,
                area_m2=listing.area_m2,
                region_code=normalized_region_code,
                source=source,
            )

            if baseline is None:
                continue  # Skip if no baseline available

            # Calculate deal delta and score
            deal_delta_pct = self._calculate_deal_delta_pct(
                baseline.avg_monthly_cost_per_m2, monthly_cost_per_m2
            )
            recommendation_score = self._calculate_recommendation_score(deal_delta_pct)

            # Build recommendation reasons
            reasons = self._build_recommendation_reasons(
                deal_delta_pct=deal_delta_pct,
                total_monthly_cost=total_monthly_cost,
                monthly_cost_per_m2=monthly_cost_per_m2,
                baseline=baseline,
            )

            scored_items.append(
                {
                    "id": listing.id,
                    "source": listing.source,
                    "source_id": listing.source_id,
                    "property_type": listing.property_type,
                    "rent_type": listing.rent_type,
                    "deposit": listing.deposit,
                    "monthly_rent": listing.monthly_rent,
                    "address": listing.address,
                    "dong": listing.dong,
                    "detail_address": listing.detail_address,
                    "area_m2": float(listing.area_m2) if listing.area_m2 else None,
                    "floor": listing.floor,
                    "total_floors": listing.total_floors,
                    "description": listing.description,
                    "latitude": float(listing.latitude) if listing.latitude else None,
                    "longitude": float(listing.longitude)
                    if listing.longitude
                    else None,
                    "is_active": listing.is_active,
                    "first_seen_at": listing.first_seen_at.isoformat()
                    if listing.first_seen_at
                    else None,
                    "last_seen_at": listing.last_seen_at.isoformat()
                    if listing.last_seen_at
                    else None,
                    "created_at": listing.created_at.isoformat()
                    if listing.created_at
                    else None,
                    "updated_at": listing.updated_at.isoformat()
                    if listing.updated_at
                    else None,
                    # Recommendation-specific fields
                    "rank": 0,  # Will be set after sorting
                    "recommendation_score": recommendation_score,
                    "total_monthly_cost": int(total_monthly_cost),
                    "monthly_cost_per_m2": float(monthly_cost_per_m2),
                    "baseline_monthly_cost_per_m2": baseline.avg_monthly_cost_per_m2,
                    "deal_delta_pct": round(deal_delta_pct, 2),
                    "baseline_scope": baseline.scope,
                    "baseline_sample_count": baseline.sample_count,
                    "recommendation_reasons": reasons,
                    "_last_seen_sort": listing.last_seen_at,
                }
            )

        # Step 5: Sort by recommendation_score DESC, total_monthly_cost ASC, last_seen_at DESC
        def sort_key(item: dict[str, object]) -> tuple[int, int, float]:
            raw_last_seen = item.get("_last_seen_sort")
            if isinstance(raw_last_seen, datetime):
                sort_last_seen = raw_last_seen
                if sort_last_seen.tzinfo is None:
                    sort_last_seen = sort_last_seen.replace(tzinfo=UTC)
                last_seen_key = -sort_last_seen.timestamp()
            else:
                last_seen_key = float("inf")

            return (
                -cast(int, item["recommendation_score"]),
                cast(int, item["total_monthly_cost"]),
                last_seen_key,
            )

        scored_items.sort(key=sort_key)

        # Step 6: Apply limit and assign ranks
        final_items = scored_items[:limit]
        for i, item in enumerate(final_items, start=1):
            item.pop("_last_seen_sort", None)
            item["rank"] = i

        return {
            "status": "success",
            "query": base_query,
            "count": len(final_items),
            "items": final_items,
            "crawl_status": crawl_status,
        }
