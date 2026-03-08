from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.repositories import BaselineComparisonStats
from src.services.place_query_recommendation_service import (
    PlaceQueryRecommendationService,
)
from src.services.recommendation_service import RecommendationService


def _make_listing(**overrides: Any) -> SimpleNamespace:
    now = datetime(2026, 3, 7, 12, 0, tzinfo=UTC)
    payload: dict[str, Any] = {
        "id": 1,
        "source": "zigbang_test_seed",
        "source_id": "seed-1",
        "property_type": "villa",
        "rent_type": "monthly",
        "deposit": 10000,
        "monthly_rent": 50,
        "address": "서울 종로구 사직동",
        "dong": "사직동",
        "detail_address": None,
        "area_m2": Decimal("40.0"),
        "floor": 5,
        "total_floors": 10,
        "description": "sample",
        "latitude": Decimal("37.572"),
        "longitude": Decimal("126.976"),
        "is_active": True,
        "first_seen_at": now - timedelta(days=5),
        "last_seen_at": now - timedelta(days=1),
        "created_at": now - timedelta(days=5),
        "updated_at": now,
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


@pytest.mark.anyio
async def test_recommend_listings_blank_region_returns_error_without_crawl_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def forbidden_evaluate(*args: Any, **kwargs: Any) -> dict[str, object]:
        raise AssertionError("evaluate_crawl_status must not run for blank region")

    monkeypatch.setattr(
        RecommendationService,
        "evaluate_crawl_status",
        forbidden_evaluate,
        raising=False,
    )

    service = RecommendationService(cast(AsyncSession, object()))
    result = await service.recommend_listings(region_code="   ")

    assert result["status"] == "error"
    assert result["count"] == 0
    assert result["items"] == []
    assert result["message"] == "region_code is required"


@pytest.mark.anyio
async def test_recommend_listings_invalid_region_returns_error_without_crawl_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def forbidden_evaluate(*args: Any, **kwargs: Any) -> dict[str, object]:
        raise AssertionError("evaluate_crawl_status must not run for invalid region")

    monkeypatch.setattr(
        RecommendationService,
        "evaluate_crawl_status",
        forbidden_evaluate,
        raising=False,
    )

    service = RecommendationService(cast(AsyncSession, object()))
    result = await service.recommend_listings(region_code="99999")

    assert result["status"] == "error"
    assert result["count"] == 0
    assert result["items"] == []
    assert result["message"] == "region_code must be a valid supported region code"


@pytest.mark.anyio
async def test_recommend_listings_needs_crawl_returns_empty_with_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_evaluate(
        self: Any,
        *,
        region_code: str | None,
        stale_hours: int = 48,
        source: str = "zigbang",
    ) -> dict[str, object]:
        return {
            "source": source,
            "region_code": region_code,
            "evaluated": True,
            "needs_crawl": True,
            "reason": "stale_data",
            "last_seen_at": None,
            "stale_threshold_hours": stale_hours,
        }

    async def forbidden_fetch(*args: Any, **kwargs: Any) -> list[object]:
        raise AssertionError("fetch_listings must not run when crawl is needed")

    monkeypatch.setattr(
        RecommendationService,
        "evaluate_crawl_status",
        fake_evaluate,
        raising=False,
    )
    monkeypatch.setattr(
        "src.services.recommendation_service.fetch_listings",
        forbidden_fetch,
    )

    service = RecommendationService(cast(AsyncSession, object()))
    result = await service.recommend_listings(region_code="11110")

    assert result["status"] == "needs_crawl"
    assert result["count"] == 0
    assert result["items"] == []
    assert isinstance(result["crawl_message"], str)
    assert result["crawl_message"]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("raw_rent_type", "expected_rent_type"),
    [
        ("월세", "monthly"),
        ("전세", "jeonse"),
        ("monthly", "monthly"),
        ("jeonse", "jeonse"),
    ],
)
async def test_recommend_listings_normalizes_rent_type_aliases(
    monkeypatch: pytest.MonkeyPatch,
    raw_rent_type: str,
    expected_rent_type: str,
) -> None:
    captured_rent_types: list[str | None] = []

    async def fake_evaluate(*args: Any, **kwargs: Any) -> dict[str, object]:
        return {
            "source": "zigbang",
            "region_code": "11110",
            "evaluated": True,
            "needs_crawl": False,
            "reason": "fresh_data",
            "last_seen_at": None,
            "stale_threshold_hours": 48,
        }

    async def fake_fetch_listings(
        _session: AsyncSession,
        **kwargs: Any,
    ) -> list[object]:
        captured_rent_types.append(cast(str | None, kwargs.get("rent_type")))
        return []

    monkeypatch.setattr(
        RecommendationService,
        "evaluate_crawl_status",
        fake_evaluate,
        raising=False,
    )
    monkeypatch.setattr(
        "src.services.recommendation_service.fetch_listings",
        fake_fetch_listings,
    )

    service = RecommendationService(cast(AsyncSession, object()))
    result = await service.recommend_listings(
        region_code="11110", rent_type=raw_rent_type
    )

    assert result["status"] == "success"
    assert captured_rent_types == [expected_rent_type, expected_rent_type]
    assert cast(dict[str, object], result["query"])["rent_type"] == expected_rent_type


@pytest.mark.anyio
async def test_recommend_listings_uses_latest_last_seen_at_for_tie_break(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    older = _make_listing(
        id=1, source_id="seed-1", last_seen_at=datetime(2026, 3, 1, tzinfo=UTC)
    )
    newer = _make_listing(
        id=2, source_id="seed-2", last_seen_at=datetime(2026, 3, 2, tzinfo=UTC)
    )

    async def fake_evaluate(*args: Any, **kwargs: Any) -> dict[str, object]:
        return {
            "source": "zigbang",
            "region_code": "11110",
            "evaluated": True,
            "needs_crawl": False,
            "reason": "fresh_data",
            "last_seen_at": None,
            "stale_threshold_hours": 48,
        }

    async def fake_fetch_listings(
        _session: AsyncSession,
        **kwargs: Any,
    ) -> list[object]:
        assert kwargs["property_type"] == "villa"
        return [older, newer]

    async def fake_fetch_baseline(
        _session: AsyncSession,
        **kwargs: Any,
    ) -> BaselineComparisonStats:
        assert kwargs["region_code"] == "11110"
        return BaselineComparisonStats(
            avg_monthly_cost_per_m2=1000.0,
            sample_count=5,
            scope="region",
        )

    monkeypatch.setattr(
        RecommendationService,
        "evaluate_crawl_status",
        fake_evaluate,
        raising=False,
    )
    monkeypatch.setattr(
        "src.services.recommendation_service.fetch_listings",
        fake_fetch_listings,
    )
    monkeypatch.setattr(
        "src.services.recommendation_service.fetch_baseline_comparison_stats",
        fake_fetch_baseline,
    )

    service = RecommendationService(cast(AsyncSession, object()))
    result = await service.recommend_listings(
        region_code="11110",
        property_types=["villa"],
        limit=10,
    )

    items = cast(list[dict[str, object]], result["items"])
    assert [item["id"] for item in items] == [2, 1]
    assert [item["rank"] for item in items] == [1, 2]


@pytest.mark.anyio
async def test_recommend_listings_normalizes_region_code_for_candidates_and_baseline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_candidate_region_codes: list[str | None] = []
    captured_baseline_region_codes: list[str] = []

    async def fake_evaluate(*args: Any, **kwargs: Any) -> dict[str, object]:
        assert kwargs["region_code"] == "11110"
        return {
            "source": "zigbang",
            "region_code": "11110",
            "evaluated": True,
            "needs_crawl": False,
            "reason": "fresh_data",
            "last_seen_at": None,
            "stale_threshold_hours": 48,
        }

    async def fake_fetch_listings(
        _session: AsyncSession,
        **kwargs: Any,
    ) -> list[object]:
        captured_candidate_region_codes.append(
            cast(str | None, kwargs.get("region_code"))
        )
        return [_make_listing()]

    async def fake_fetch_baseline(
        _session: AsyncSession,
        **kwargs: Any,
    ) -> BaselineComparisonStats:
        captured_baseline_region_codes.append(cast(str, kwargs["region_code"]))
        return BaselineComparisonStats(
            avg_monthly_cost_per_m2=1000.0,
            sample_count=5,
            scope="region",
        )

    monkeypatch.setattr(
        RecommendationService,
        "evaluate_crawl_status",
        fake_evaluate,
        raising=False,
    )
    monkeypatch.setattr(
        "src.services.recommendation_service.fetch_listings",
        fake_fetch_listings,
    )
    monkeypatch.setattr(
        "src.services.recommendation_service.fetch_baseline_comparison_stats",
        fake_fetch_baseline,
    )

    service = RecommendationService(cast(AsyncSession, object()))
    result = await service.recommend_listings(
        region_code=" 11110 ",
        property_types=["villa"],
        limit=10,
    )

    assert result["status"] == "success"
    assert captured_candidate_region_codes == ["11110"]
    assert captured_baseline_region_codes == ["11110"]


def _make_ranked_item(
    *,
    item_id: int,
    source_id: str,
    recommendation_score: int,
    total_monthly_cost: int,
    last_seen_at: str,
) -> dict[str, object]:
    return {
        "id": item_id,
        "source": "zigbang_test_seed",
        "source_id": source_id,
        "property_type": "villa",
        "rent_type": "monthly",
        "deposit": 10000,
        "monthly_rent": 50,
        "address": "서울 종로구 사직동",
        "dong": "사직동",
        "detail_address": None,
        "area_m2": 40.0,
        "floor": 5,
        "total_floors": 10,
        "description": "sample",
        "latitude": 37.572,
        "longitude": 126.976,
        "is_active": True,
        "first_seen_at": "2026-03-01T00:00:00+00:00",
        "last_seen_at": last_seen_at,
        "created_at": "2026-03-01T00:00:00+00:00",
        "updated_at": "2026-03-07T00:00:00+00:00",
        "rank": 99,
        "recommendation_score": recommendation_score,
        "total_monthly_cost": total_monthly_cost,
        "monthly_cost_per_m2": 1000.0,
        "baseline_monthly_cost_per_m2": 1100.0,
        "deal_delta_pct": 10.0,
        "baseline_scope": "region",
        "baseline_sample_count": 5,
        "recommendation_reasons": ["sample"],
    }


@pytest.mark.anyio
async def test_recommend_by_place_query_returns_clarification_needed_from_resolver() -> (
    None
):
    class FakeResolver:
        async def resolve(self, place_query: str) -> dict[str, object]:
            assert place_query == "평촌역"
            return {
                "status": "clarification_needed",
                "parsed_places": ["평촌역"],
                "resolved_dongs": [],
                "question": "무슨 동이 맞습니까?",
                "clarification_groups": [
                    {
                        "station_name": "평촌역",
                        "options": [
                            {
                                "station_name": "평촌역",
                                "region_code": "41190",
                                "dong": "호계동",
                                "label": "경기도 안양시 동안구 호계동",
                            }
                        ],
                    }
                ],
            }

    service = PlaceQueryRecommendationService(
        cast(AsyncSession, object()),
        place_query_resolver=FakeResolver(),
    )

    result = await service.recommend_by_place_query(place_query="평촌역")

    assert result["status"] == "clarification_needed"
    assert result["count"] == 0
    assert result["items"] == []
    assert result["question"] == "무슨 동이 맞습니까?"
    assert result["parsed_places"] == ["평촌역"]


@pytest.mark.anyio
async def test_recommend_by_place_query_auto_resolves_single_candidate_and_reuses_recommendations() -> (
    None
):
    class FakeResolver:
        async def resolve(self, place_query: str) -> dict[str, object]:
            assert place_query == "평촌역 주변 추천"
            return {
                "status": "resolved",
                "parsed_places": ["평촌역"],
                "resolved_dongs": [
                    {
                        "station_name": "평촌역",
                        "region_code": "41190",
                        "dong": "호계동",
                        "label": "경기도 안양시 동안구 호계동",
                    }
                ],
                "clarification_groups": [],
            }

    class FakeRecommendationService:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str | None]] = []

        async def evaluate_crawl_status(
            self, *, region_code: str | None, **kwargs: Any
        ) -> dict[str, object]:
            _ = kwargs
            return {
                "source": "zigbang",
                "region_code": region_code,
                "evaluated": True,
                "needs_crawl": False,
                "reason": "fresh_data",
                "last_seen_at": "2026-03-07T00:00:00+00:00",
                "stale_threshold_hours": 48,
            }

        async def recommend_listings(self, **kwargs: Any) -> dict[str, object]:
            self.calls.append((kwargs["region_code"], kwargs.get("dong")))
            return {
                "status": "success",
                "query": kwargs,
                "count": 1,
                "items": [
                    _make_ranked_item(
                        item_id=21,
                        source_id="seed-21",
                        recommendation_score=87,
                        total_monthly_cost=910,
                        last_seen_at="2026-03-07T09:00:00+00:00",
                    )
                ],
                "crawl_status": {
                    "needs_crawl": False,
                    "reason": "fresh_data",
                },
            }

    fake_recommendation_service = FakeRecommendationService()
    service = PlaceQueryRecommendationService(
        cast(AsyncSession, object()),
        place_query_resolver=FakeResolver(),
        recommendation_service=fake_recommendation_service,
    )

    result = await service.recommend_by_place_query(place_query="평촌역 주변 추천")

    assert fake_recommendation_service.calls == [("41190", "호계동")]
    assert result["status"] == "success"
    assert result["parsed_places"] == ["평촌역"]
    assert result["count"] == 1
    assert [item["id"] for item in cast(list[dict[str, object]], result["items"])] == [
        21
    ]


@pytest.mark.anyio
async def test_recommend_by_place_query_uses_resolved_dongs_without_resolver_and_deduplicates_items() -> (
    None
):
    class ForbiddenResolver:
        async def resolve(self, place_query: str) -> dict[str, object]:
            raise AssertionError(
                f"resolver must not be called when resolved_dongs is provided: {place_query}"
            )

    class FakeRecommendationService:
        async def evaluate_crawl_status(
            self, *, region_code: str | None, **kwargs: Any
        ) -> dict[str, object]:
            _ = kwargs
            return {
                "source": "zigbang",
                "region_code": region_code,
                "evaluated": True,
                "needs_crawl": False,
                "reason": "fresh_data",
                "last_seen_at": "2026-03-07T00:00:00+00:00",
                "stale_threshold_hours": 48,
            }

        async def recommend_listings(self, **kwargs: Any) -> dict[str, object]:
            if kwargs["dong"] == "호계동":
                items = [
                    _make_ranked_item(
                        item_id=10,
                        source_id="seed-10",
                        recommendation_score=90,
                        total_monthly_cost=950,
                        last_seen_at="2026-03-07T08:00:00+00:00",
                    ),
                    _make_ranked_item(
                        item_id=11,
                        source_id="seed-11",
                        recommendation_score=80,
                        total_monthly_cost=980,
                        last_seen_at="2026-03-07T07:00:00+00:00",
                    ),
                ]
            else:
                items = [
                    _make_ranked_item(
                        item_id=10,
                        source_id="seed-10",
                        recommendation_score=90,
                        total_monthly_cost=950,
                        last_seen_at="2026-03-07T08:00:00+00:00",
                    ),
                    _make_ranked_item(
                        item_id=12,
                        source_id="seed-12",
                        recommendation_score=95,
                        total_monthly_cost=920,
                        last_seen_at="2026-03-07T09:00:00+00:00",
                    ),
                ]
            return {
                "status": "success",
                "query": kwargs,
                "count": len(items),
                "items": items,
                "crawl_status": {
                    "needs_crawl": False,
                    "reason": "fresh_data",
                },
            }

    service = PlaceQueryRecommendationService(
        cast(AsyncSession, object()),
        place_query_resolver=ForbiddenResolver(),
        recommendation_service=FakeRecommendationService(),
    )

    result = await service.recommend_by_place_query(
        place_query="평촌역, 범계역 주변에서 추천해줘",
        resolved_dongs=[
            {
                "station_name": "평촌역",
                "region_code": "41190",
                "dong": "호계동",
            },
            {
                "station_name": "범계역",
                "region_code": "41190",
                "dong": "평촌동",
            },
        ],
        limit=5,
    )

    items = cast(list[dict[str, object]], result["items"])
    assert result["status"] == "success"
    assert result["count"] == 3
    assert [item["id"] for item in items] == [12, 10, 11]
    assert [item["rank"] for item in items] == [1, 2, 3]


@pytest.mark.anyio
async def test_recommend_by_place_query_returns_needs_crawl_when_any_target_is_stale() -> (
    None
):
    class ForbiddenResolver:
        async def resolve(self, place_query: str) -> dict[str, object]:
            raise AssertionError(
                f"resolver must not be called when resolved_dongs is provided: {place_query}"
            )

    class FakeRecommendationService:
        async def evaluate_crawl_status(
            self, *, region_code: str | None, **kwargs: Any
        ) -> dict[str, object]:
            _ = kwargs
            if region_code == "11680":
                return {
                    "source": "zigbang",
                    "region_code": region_code,
                    "evaluated": True,
                    "needs_crawl": True,
                    "reason": "stale_data",
                    "last_seen_at": "2026-03-01T00:00:00+00:00",
                    "stale_threshold_hours": 48,
                }
            return {
                "source": "zigbang",
                "region_code": region_code,
                "evaluated": True,
                "needs_crawl": False,
                "reason": "fresh_data",
                "last_seen_at": "2026-03-07T00:00:00+00:00",
                "stale_threshold_hours": 48,
            }

        async def recommend_listings(self, **kwargs: Any) -> dict[str, object]:
            raise AssertionError(f"recommend_listings must not run: {kwargs}")

    service = PlaceQueryRecommendationService(
        cast(AsyncSession, object()),
        place_query_resolver=ForbiddenResolver(),
        recommendation_service=FakeRecommendationService(),
    )

    result = await service.recommend_by_place_query(
        place_query="평촌역, 강남역 주변에서 추천해줘",
        resolved_dongs=[
            {
                "station_name": "평촌역",
                "region_code": "41190",
                "dong": "호계동",
            },
            {
                "station_name": "강남역",
                "region_code": "11680",
                "dong": "역삼동",
            },
        ],
    )

    assert result["status"] == "needs_crawl"
    assert result["count"] == 0
    assert result["items"] == []
    assert isinstance(result["crawl_message"], str)
    assert result["crawl_targets"] == [
        {
            "station_name": "강남역",
            "region_code": "11680",
            "dong": "역삼동",
            "reason": "stale_data",
            "last_seen_at": "2026-03-01T00:00:00+00:00",
        }
    ]


@pytest.mark.anyio
async def test_recommend_by_place_query_returns_needs_crawl_when_any_target_has_no_dong_data() -> (
    None
):
    class ForbiddenResolver:
        async def resolve(self, place_query: str) -> dict[str, object]:
            raise AssertionError(
                f"resolver must not be called when resolved_dongs is provided: {place_query}"
            )

    class FakeRecommendationService:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str | None]] = []

        async def evaluate_crawl_status(
            self, *, region_code: str | None, **kwargs: Any
        ) -> dict[str, object]:
            _ = kwargs
            return {
                "source": "zigbang",
                "region_code": region_code,
                "evaluated": True,
                "needs_crawl": False,
                "reason": "fresh_data",
                "last_seen_at": "2026-03-07T00:00:00+00:00",
                "stale_threshold_hours": 48,
            }

        async def recommend_listings(self, **kwargs: Any) -> dict[str, object]:
            self.calls.append((kwargs["region_code"], kwargs.get("dong")))
            if kwargs.get("dong") == "역삼동":
                return {
                    "status": "success",
                    "query": kwargs,
                    "count": 0,
                    "items": [],
                    "crawl_status": {
                        "needs_crawl": False,
                        "reason": "fresh_data",
                    },
                }

            return {
                "status": "success",
                "query": kwargs,
                "count": 1,
                "items": [
                    _make_ranked_item(
                        item_id=21,
                        source_id="seed-21",
                        recommendation_score=87,
                        total_monthly_cost=910,
                        last_seen_at="2026-03-07T09:00:00+00:00",
                    )
                ],
                "crawl_status": {
                    "needs_crawl": False,
                    "reason": "fresh_data",
                },
            }

    fake_recommendation_service = FakeRecommendationService()
    service = PlaceQueryRecommendationService(
        cast(AsyncSession, object()),
        place_query_resolver=ForbiddenResolver(),
        recommendation_service=fake_recommendation_service,
    )

    result = await service.recommend_by_place_query(
        place_query="평촌역, 강남역 주변에서 추천해줘",
        resolved_dongs=[
            {
                "station_name": "평촌역",
                "region_code": "41190",
                "dong": "호계동",
            },
            {
                "station_name": "강남역",
                "region_code": "11680",
                "dong": "역삼동",
            },
        ],
    )

    assert fake_recommendation_service.calls == [
        ("41190", "호계동"),
        ("11680", "역삼동"),
    ]
    assert result["status"] == "needs_crawl"
    assert result["count"] == 0
    assert result["items"] == []
    assert isinstance(result["crawl_message"], str)
    assert result["crawl_targets"] == [
        {
            "station_name": "강남역",
            "region_code": "11680",
            "dong": "역삼동",
            "reason": "no_dong_data",
            "last_seen_at": None,
        }
    ]


@pytest.mark.anyio
async def test_recommend_by_place_query_returns_needs_crawl_when_any_target_reports_zero_count() -> (
    None
):
    class ForbiddenResolver:
        async def resolve(self, place_query: str) -> dict[str, object]:
            raise AssertionError(
                f"resolver must not be called when resolved_dongs is provided: {place_query}"
            )

    class FakeRecommendationService:
        async def evaluate_crawl_status(
            self, *, region_code: str | None, **kwargs: Any
        ) -> dict[str, object]:
            _ = kwargs
            return {
                "source": "zigbang",
                "region_code": region_code,
                "evaluated": True,
                "needs_crawl": False,
                "reason": "fresh_data",
                "last_seen_at": "2026-03-07T00:00:00+00:00",
                "stale_threshold_hours": 48,
            }

        async def recommend_listings(self, **kwargs: Any) -> dict[str, object]:
            if kwargs.get("dong") == "역삼동":
                return {
                    "status": "success",
                    "query": kwargs,
                    "count": 0,
                    "items": [
                        _make_ranked_item(
                            item_id=31,
                            source_id="seed-31",
                            recommendation_score=90,
                            total_monthly_cost=900,
                            last_seen_at="2026-03-07T10:00:00+00:00",
                        )
                    ],
                    "crawl_status": {
                        "needs_crawl": False,
                        "reason": "fresh_data",
                    },
                }

            return {
                "status": "success",
                "query": kwargs,
                "count": 1,
                "items": [
                    _make_ranked_item(
                        item_id=21,
                        source_id="seed-21",
                        recommendation_score=87,
                        total_monthly_cost=910,
                        last_seen_at="2026-03-07T09:00:00+00:00",
                    )
                ],
                "crawl_status": {
                    "needs_crawl": False,
                    "reason": "fresh_data",
                },
            }

    service = PlaceQueryRecommendationService(
        cast(AsyncSession, object()),
        place_query_resolver=ForbiddenResolver(),
        recommendation_service=FakeRecommendationService(),
    )

    result = await service.recommend_by_place_query(
        place_query="평촌역, 강남역 주변에서 추천해줘",
        resolved_dongs=[
            {
                "station_name": "평촌역",
                "region_code": "41190",
                "dong": "호계동",
            },
            {
                "station_name": "강남역",
                "region_code": "11680",
                "dong": "역삼동",
            },
        ],
    )

    assert result["status"] == "needs_crawl"
    assert result["count"] == 0
    assert result["items"] == []
    assert result["crawl_targets"] == [
        {
            "station_name": "강남역",
            "region_code": "11680",
            "dong": "역삼동",
            "reason": "no_dong_data",
            "last_seen_at": None,
        }
    ]
