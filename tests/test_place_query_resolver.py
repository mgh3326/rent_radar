from __future__ import annotations

import httpx
import pytest

from src.services.place_query_resolver import (
    PlaceQueryResolver,
    extract_station_queries,
)

pytestmark = pytest.mark.anyio

SearchResultValue = list[dict[str, object]] | Exception
RegionResultValue = dict[str, object] | Exception | None


class FakeKakaoClient:
    def __init__(
        self,
        *,
        search_results: dict[str, SearchResultValue] | None = None,
        region_results: dict[tuple[str, str, str], RegionResultValue] | None = None,
    ) -> None:
        self._search_results: dict[str, SearchResultValue] = search_results or {}
        self._region_results: dict[tuple[str, str, str], RegionResultValue] = (
            region_results or {}
        )
        self.search_calls: list[tuple[str, str]] = []
        self.region_calls: list[tuple[str, str, str]] = []

    async def search_keyword(
        self, query: str, *, category_group_code: str = "SW8"
    ) -> list[dict[str, object]]:
        self.search_calls.append((query, category_group_code))
        result = self._search_results.get(query, [])
        if isinstance(result, Exception):
            raise result
        return result

    async def coord_to_region(
        self, longitude: str, latitude: str, *, region_type: str = "H"
    ) -> dict[str, object] | None:
        self.region_calls.append((longitude, latitude, region_type))
        result = self._region_results.get((longitude, latitude, region_type))
        if isinstance(result, Exception):
            raise result
        return result


def _make_station_doc(
    *,
    place_name: str,
    x: str,
    y: str,
    address_name: str,
    category_group_code: str = "SW8",
) -> dict[str, object]:
    return {
        "place_name": place_name,
        "x": x,
        "y": y,
        "address_name": address_name,
        "category_group_code": category_group_code,
    }


def _make_region_doc(
    *,
    sido: str,
    sigungu: str,
    dong: str,
    region_type: str = "H",
) -> dict[str, object]:
    return {
        "region_type": region_type,
        "region_1depth_name": sido,
        "region_2depth_name": sigungu,
        "region_3depth_name": dong,
        "address_name": f"{sido} {sigungu} {dong}",
        "code": "ignored-by-project",
    }


def _make_http_error(status_code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://dapi.kakao.com/test")
    response = httpx.Response(status_code, request=request)
    return httpx.HTTPStatusError(
        f"status={status_code}",
        request=request,
        response=response,
    )


async def test_extract_station_queries_pulls_multiple_station_tokens() -> None:
    assert extract_station_queries("평촌역, 범계역 주변에서 추천해줘") == [
        "평촌역",
        "범계역",
    ]


async def test_extract_station_queries_falls_back_to_full_query_without_station_token() -> (
    None
):
    assert extract_station_queries("판교 테크노밸리 주변에서 추천해줘") == [
        "판교 테크노밸리 주변에서 추천해줘"
    ]


@pytest.mark.anyio
async def test_resolve_returns_clarification_groups_for_ambiguous_station() -> None:
    client = FakeKakaoClient(
        search_results={
            "평촌역": [
                _make_station_doc(
                    place_name="평촌역",
                    x="126.961",
                    y="37.394",
                    address_name="경기 안양시 동안구 호계동 1039",
                ),
                _make_station_doc(
                    place_name="평촌역",
                    x="126.970",
                    y="37.390",
                    address_name="경기 안양시 동안구 평촌동 82",
                ),
            ]
        },
        region_results={
            ("126.961", "37.394", "H"): _make_region_doc(
                sido="경기도", sigungu="안양시 동안구", dong="호계동"
            ),
            ("126.970", "37.390", "H"): _make_region_doc(
                sido="경기도", sigungu="안양시 동안구", dong="평촌동"
            ),
        },
    )
    resolver = PlaceQueryResolver(api_key="kakao-test-key", client=client)

    result = await resolver.resolve("평촌역")

    assert result["status"] == "clarification_needed"
    assert result["question"] == "무슨 동이 맞습니까?"
    assert result["parsed_places"] == ["평촌역"]
    assert result["resolved_dongs"] == []
    groups = result["clarification_groups"]
    assert isinstance(groups, list)
    assert len(groups) == 1
    first_group = groups[0]
    assert first_group["station_name"] == "평촌역"
    assert [option["dong"] for option in first_group["options"]] == ["호계동", "평촌동"]
    assert [option["region_code"] for option in first_group["options"]] == [
        "41190",
        "41190",
    ]
    assert [option["label"] for option in first_group["options"]] == [
        "경기도 안양시 동안구 호계동",
        "경기도 안양시 동안구 평촌동",
    ]


@pytest.mark.anyio
async def test_resolve_returns_error_when_api_key_missing() -> None:
    resolver = PlaceQueryResolver(api_key="")

    result = await resolver.resolve("평촌역")

    assert result["status"] == "error"
    assert result["parsed_places"] == ["평촌역"]
    assert result["message"] == "KAKAO_REST_API_KEY is required"


@pytest.mark.anyio
async def test_resolve_returns_error_when_station_not_found() -> None:
    resolver = PlaceQueryResolver(
        api_key="kakao-test-key",
        client=FakeKakaoClient(search_results={"평촌역": []}),
    )

    result = await resolver.resolve("평촌역")

    assert result["status"] == "error"
    assert result["parsed_places"] == ["평촌역"]
    assert result["message"] == "No Kakao station match found for '평촌역'"


@pytest.mark.anyio
@pytest.mark.parametrize("status_code", [429, 503])
async def test_resolve_returns_error_for_kakao_http_failures(status_code: int) -> None:
    resolver = PlaceQueryResolver(
        api_key="kakao-test-key",
        client=FakeKakaoClient(
            search_results={"평촌역": _make_http_error(status_code)}
        ),
    )

    result = await resolver.resolve("평촌역")

    assert result["status"] == "error"
    assert result["parsed_places"] == ["평촌역"]
    assert (
        result["message"] == f"Kakao Local API request failed with status {status_code}"
    )
