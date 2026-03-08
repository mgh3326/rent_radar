from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol, cast

from sqlalchemy.ext.asyncio import AsyncSession

from src.config.region_codes import REGION_CODE_TO_NAME, is_valid_region_code
from src.services.place_query_resolver import (
    PlaceQueryResolver,
    extract_station_queries,
)
from src.services.recommendation_service import RecommendationService

_RECOMMENDATION_FETCH_LIMIT = 500
_NEEDS_CRAWL_MESSAGE = (
    "선택한 지역 중 데이터가 없거나 오래된 지역이 있어 크롤링이 필요합니다."
)


class PlaceQueryRecommendationService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        place_query_resolver: "PlaceResolver | None" = None,
        recommendation_service: "RecommendationLookupService | None" = None,
    ) -> None:
        self._session = session
        self._place_query_resolver = place_query_resolver or PlaceQueryResolver()
        self._recommendation_service = recommendation_service or RecommendationService(
            session
        )

    async def recommend_by_place_query(
        self,
        *,
        place_query: str,
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
        resolved_dongs: Sequence[Mapping[str, str]] | None = None,
        source: str = "zigbang",
    ) -> dict[str, object]:
        normalized_place_query = place_query.strip()
        parsed_places = extract_station_queries(normalized_place_query)
        normalized_resolved_dongs, resolved_error = self._normalize_resolved_dongs(
            resolved_dongs
        )
        query: dict[str, object] = {
            "place_query": normalized_place_query or None,
            "parsed_places": parsed_places,
            "resolved_dongs": normalized_resolved_dongs,
            "property_types": property_types,
            "rent_type": rent_type,
            "min_deposit": min_deposit,
            "max_deposit": max_deposit,
            "min_monthly_rent": min_monthly_rent,
            "max_monthly_rent": max_monthly_rent,
            "min_area": float(min_area) if min_area is not None else None,
            "max_area": float(max_area) if max_area is not None else None,
            "min_floor": min_floor,
            "max_floor": max_floor,
            "limit": limit,
            "source": source,
        }

        if not normalized_place_query:
            return self._error_response(
                query=query,
                message="place_query is required",
                parsed_places=parsed_places,
                resolved_dongs=normalized_resolved_dongs,
            )

        if resolved_error is not None:
            return self._error_response(
                query=query,
                message=resolved_error,
                parsed_places=parsed_places,
                resolved_dongs=normalized_resolved_dongs,
            )

        if normalized_resolved_dongs:
            resolution_result: dict[str, object] = {
                "status": "resolved",
                "parsed_places": parsed_places,
                "resolved_dongs": normalized_resolved_dongs,
                "clarification_groups": [],
            }
        else:
            resolution_result = await self._place_query_resolver.resolve(
                normalized_place_query
            )

        resolution_status = cast(str, resolution_result.get("status", "error"))
        resolved_targets = cast(
            list[dict[str, str]], resolution_result.get("resolved_dongs", [])
        )
        parsed_places = cast(
            list[str], resolution_result.get("parsed_places", parsed_places)
        )
        query["parsed_places"] = parsed_places
        query["resolved_dongs"] = resolved_targets

        if resolution_status == "error":
            return self._error_response(
                query=query,
                message=str(
                    resolution_result.get("message", "Failed to resolve place_query")
                ),
                parsed_places=parsed_places,
                resolved_dongs=resolved_targets,
            )

        if resolution_status == "clarification_needed":
            return {
                "status": "clarification_needed",
                "query": query,
                "count": 0,
                "items": [],
                "question": resolution_result.get("question", "무슨 동이 맞습니까?"),
                "clarification_groups": resolution_result.get(
                    "clarification_groups", []
                ),
                "parsed_places": parsed_places,
                "resolved_dongs": resolved_targets,
            }

        unique_targets = self._unique_targets(resolved_targets)
        crawl_targets: list[dict[str, object]] = []
        for target in unique_targets:
            crawl_status = await self._recommendation_service.evaluate_crawl_status(
                region_code=target["region_code"],
                source=source,
            )
            if crawl_status.get("needs_crawl") is True:
                crawl_targets.append(
                    self._build_crawl_target(
                        target,
                        reason=str(crawl_status.get("reason") or "stale_data"),
                        last_seen_at=crawl_status.get("last_seen_at"),
                    )
                )

        if crawl_targets:
            return {
                "status": "needs_crawl",
                "query": query,
                "count": 0,
                "items": [],
                "crawl_targets": crawl_targets,
                "crawl_message": _NEEDS_CRAWL_MESSAGE,
                "parsed_places": parsed_places,
                "resolved_dongs": resolved_targets,
            }

        merged_items: dict[tuple[object, ...], dict[str, object]] = {}
        for target in unique_targets:
            target_result = await self._recommendation_service.recommend_listings(
                region_code=target["region_code"],
                dong=target["dong"],
                property_types=property_types,
                rent_type=rent_type,
                min_deposit=min_deposit,
                max_deposit=max_deposit,
                min_monthly_rent=min_monthly_rent,
                max_monthly_rent=max_monthly_rent,
                min_area=min_area,
                max_area=max_area,
                min_floor=min_floor,
                max_floor=max_floor,
                limit=max(limit, _RECOMMENDATION_FETCH_LIMIT),
                source=source,
            )
            if target_result.get("status") != "success":
                return {
                    "status": str(target_result.get("status", "error")),
                    "query": query,
                    "count": self._coerce_int(target_result.get("count")),
                    "items": cast(
                        list[dict[str, object]], target_result.get("items", [])
                    ),
                    "parsed_places": parsed_places,
                    "resolved_dongs": resolved_targets,
                    "message": target_result.get("message"),
                }

            target_items = cast(list[dict[str, object]], target_result.get("items", []))
            has_zero_count = (
                "count" in target_result
                and self._coerce_int(target_result.get("count")) == 0
            )
            if has_zero_count or not target_items:
                crawl_targets.append(
                    self._build_crawl_target(
                        target,
                        reason="no_dong_data",
                        last_seen_at=None,
                    )
                )
                continue

            for item in target_items:
                dedupe_key = self._item_identity(item)
                existing_item = merged_items.get(dedupe_key)
                if existing_item is None or self._recommendation_sort_key(
                    item
                ) < self._recommendation_sort_key(existing_item):
                    merged_items[dedupe_key] = dict(item)

        if crawl_targets:
            return {
                "status": "needs_crawl",
                "query": query,
                "count": 0,
                "items": [],
                "crawl_targets": crawl_targets,
                "crawl_message": _NEEDS_CRAWL_MESSAGE,
                "parsed_places": parsed_places,
                "resolved_dongs": resolved_targets,
            }

        final_items = list(merged_items.values())
        final_items.sort(key=self._recommendation_sort_key)
        final_items = final_items[:limit]
        for index, item in enumerate(final_items, start=1):
            item["rank"] = index

        return {
            "status": "success",
            "query": query,
            "count": len(final_items),
            "items": final_items,
            "parsed_places": parsed_places,
            "resolved_dongs": resolved_targets,
        }

    def _normalize_resolved_dongs(
        self, resolved_dongs: Sequence[Mapping[str, str]] | None
    ) -> tuple[list[dict[str, str]], str | None]:
        if not resolved_dongs:
            return [], None

        normalized_dongs: list[dict[str, str]] = []
        seen_targets: set[tuple[str, str, str]] = set()
        for raw_target in resolved_dongs:
            station_name = str(raw_target.get("station_name", "")).strip()
            region_code = str(raw_target.get("region_code", "")).strip()
            dong = str(raw_target.get("dong", "")).strip()
            if not station_name or not region_code or not dong:
                return (
                    [],
                    "resolved_dongs entries require station_name, region_code, and dong",
                )
            if not is_valid_region_code(region_code):
                return [], "resolved_dongs entries must use supported region codes"

            target_key = (station_name, region_code, dong)
            if target_key in seen_targets:
                continue
            seen_targets.add(target_key)
            label = str(raw_target.get("label", "")).strip()
            if not label:
                region_name = REGION_CODE_TO_NAME.get(region_code, region_code)
                label = f"{region_name} {dong}"
            normalized_dongs.append(
                {
                    "station_name": station_name,
                    "region_code": region_code,
                    "dong": dong,
                    "label": label,
                }
            )
        return normalized_dongs, None

    def _unique_targets(
        self, resolved_targets: list[dict[str, str]]
    ) -> list[dict[str, str]]:
        unique_targets: list[dict[str, str]] = []
        seen_keys: set[tuple[str, str]] = set()
        for target in resolved_targets:
            target_key = (target["region_code"], target["dong"])
            if target_key in seen_keys:
                continue
            seen_keys.add(target_key)
            unique_targets.append(target)
        return unique_targets

    def _item_identity(self, item: dict[str, object]) -> tuple[object, ...]:
        raw_id = item.get("id")
        if raw_id is not None:
            return ("id", raw_id)
        return ("source", item.get("source"), item.get("source_id"))

    def _build_crawl_target(
        self,
        target: Mapping[str, str],
        *,
        reason: str,
        last_seen_at: object,
    ) -> dict[str, object]:
        return {
            "station_name": target["station_name"],
            "region_code": target["region_code"],
            "dong": target["dong"],
            "reason": reason,
            "last_seen_at": last_seen_at,
        }

    def _recommendation_sort_key(
        self, item: dict[str, object]
    ) -> tuple[int, int, float]:
        recommendation_score = self._coerce_int(item.get("recommendation_score"))
        total_monthly_cost = self._coerce_int(item.get("total_monthly_cost"))
        raw_last_seen = item.get("last_seen_at")
        if isinstance(raw_last_seen, str):
            try:
                parsed_last_seen = datetime.fromisoformat(raw_last_seen)
                if parsed_last_seen.tzinfo is None:
                    parsed_last_seen = parsed_last_seen.replace(tzinfo=UTC)
                last_seen_sort = -parsed_last_seen.timestamp()
            except ValueError:
                last_seen_sort = float("inf")
        elif isinstance(raw_last_seen, datetime):
            parsed_last_seen = raw_last_seen
            if parsed_last_seen.tzinfo is None:
                parsed_last_seen = parsed_last_seen.replace(tzinfo=UTC)
            last_seen_sort = -parsed_last_seen.timestamp()
        else:
            last_seen_sort = float("inf")

        return (-recommendation_score, total_monthly_cost, last_seen_sort)

    def _coerce_int(self, value: object) -> int:
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, (int, float, Decimal, str)):
            try:
                return int(value)
            except ValueError:
                return 0
        return 0

    def _error_response(
        self,
        *,
        query: Mapping[str, object],
        message: str,
        parsed_places: list[str],
        resolved_dongs: list[dict[str, str]],
    ) -> dict[str, object]:
        return {
            "status": "error",
            "query": dict(query),
            "count": 0,
            "items": [],
            "message": message,
            "parsed_places": parsed_places,
            "resolved_dongs": resolved_dongs,
        }


class PlaceResolver(Protocol):
    async def resolve(self, place_query: str) -> dict[str, object]: ...


class RecommendationLookupService(Protocol):
    async def evaluate_crawl_status(
        self,
        *,
        region_code: str | None,
        stale_hours: int = 48,
        source: str = "zigbang",
    ) -> dict[str, object]: ...

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
    ) -> dict[str, object]: ...
