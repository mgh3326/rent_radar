from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Protocol, cast

import httpx

from src.config import get_settings
from src.config.region_codes import REGION_CODE_TO_NAME, is_valid_region_code

_STATION_TOKEN_RE = re.compile(r"([^\s,\/]+역)")
_WHITESPACE_RE = re.compile(r"\s+")


def _normalize_region_name(value: str) -> str:
    return _WHITESPACE_RE.sub("", value.strip())


_NORMALIZED_REGION_NAME_TO_CODE = {
    _normalize_region_name(full_name): region_code
    for region_code, full_name in REGION_CODE_TO_NAME.items()
}


def extract_station_queries(place_query: str) -> list[str]:
    normalized_query = place_query.strip()
    if not normalized_query:
        return []

    matches = _STATION_TOKEN_RE.findall(normalized_query)
    if not matches:
        return [normalized_query]

    deduped_matches: list[str] = []
    seen: set[str] = set()
    for raw_match in matches:
        station_name = raw_match.strip()
        if not station_name or station_name in seen:
            continue
        seen.add(station_name)
        deduped_matches.append(station_name)
    return deduped_matches


class KakaoLocalClient:
    BASE_URL = "https://dapi.kakao.com/v2/local"

    def __init__(self, api_key: str, *, timeout_seconds: float) -> None:
        self._api_key = api_key
        self._timeout = httpx.Timeout(timeout_seconds)

    async def search_keyword(
        self, query: str, *, category_group_code: str = "SW8"
    ) -> list[dict[str, object]]:
        data = await self._request_json(
            f"{self.BASE_URL}/search/keyword.json",
            params={
                "query": query,
                "category_group_code": category_group_code,
                "size": 15,
                "page": 1,
                "sort": "accuracy",
            },
        )
        documents = data.get("documents")
        if not isinstance(documents, list):
            return []
        return [
            cast(dict[str, object], document)
            for document in documents
            if isinstance(document, dict)
        ]

    async def coord_to_region(
        self, longitude: str, latitude: str, *, region_type: str = "H"
    ) -> dict[str, object] | None:
        data = await self._request_json(
            f"{self.BASE_URL}/geo/coord2regioncode.json",
            params={"x": longitude, "y": latitude},
        )
        documents = data.get("documents")
        if not isinstance(documents, list):
            return None
        for document in documents:
            if not isinstance(document, dict):
                continue
            if str(document.get("region_type", "")).strip() == region_type:
                return cast(dict[str, object], document)
        return None

    async def _request_json(
        self, url: str, *, params: dict[str, str | int | float]
    ) -> dict[str, object]:
        async with httpx.AsyncClient(
            timeout=self._timeout,
            headers={"Authorization": f"KakaoAK {self._api_key}"},
        ) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            return {}
        return cast(dict[str, object], payload)


class PlaceQueryResolver:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        client: "StationLookupClient | None" = None,
    ) -> None:
        settings = get_settings()
        resolved_api_key = settings.kakao_rest_api_key if api_key is None else api_key
        self._api_key = resolved_api_key.strip()
        self._client = client or KakaoLocalClient(
            self._api_key,
            timeout_seconds=settings.kakao_local_timeout_seconds,
        )

    async def resolve(self, place_query: str) -> dict[str, object]:
        parsed_places = extract_station_queries(place_query)
        if not parsed_places:
            return {
                "status": "error",
                "parsed_places": [],
                "resolved_dongs": [],
                "message": "place_query is required",
            }

        if not self._api_key:
            return {
                "status": "error",
                "parsed_places": parsed_places,
                "resolved_dongs": [],
                "message": "KAKAO_REST_API_KEY is required",
            }

        resolved_dongs: list[dict[str, str]] = []
        clarification_groups: list[dict[str, object]] = []
        for parsed_place in parsed_places:
            try:
                candidates = await self._resolve_candidates(parsed_place)
            except httpx.HTTPStatusError as exc:
                return {
                    "status": "error",
                    "parsed_places": parsed_places,
                    "resolved_dongs": resolved_dongs,
                    "message": f"Kakao Local API request failed with status {exc.response.status_code}",
                }
            except httpx.HTTPError as exc:
                return {
                    "status": "error",
                    "parsed_places": parsed_places,
                    "resolved_dongs": resolved_dongs,
                    "message": f"Kakao Local API request failed: {exc}",
                }

            if not candidates:
                return {
                    "status": "error",
                    "parsed_places": parsed_places,
                    "resolved_dongs": resolved_dongs,
                    "message": f"No Kakao station match found for '{parsed_place}'",
                }

            if len(candidates) == 1:
                resolved_dongs.extend(candidates)
                continue

            clarification_groups.append(
                {
                    "station_name": candidates[0]["station_name"],
                    "options": candidates,
                }
            )

        if clarification_groups:
            return {
                "status": "clarification_needed",
                "parsed_places": parsed_places,
                "resolved_dongs": resolved_dongs,
                "question": "무슨 동이 맞습니까?",
                "clarification_groups": clarification_groups,
            }

        return {
            "status": "resolved",
            "parsed_places": parsed_places,
            "resolved_dongs": resolved_dongs,
            "clarification_groups": [],
        }

    async def _resolve_candidates(self, station_query: str) -> list[dict[str, str]]:
        client = self._client
        search_results = await client.search_keyword(
            station_query,
            category_group_code="SW8",
        )

        candidates: list[dict[str, str]] = []
        seen_candidates: set[tuple[str, str, str]] = set()
        for document in search_results:
            category_group_code = str(document.get("category_group_code", "")).strip()
            if category_group_code and category_group_code != "SW8":
                continue

            longitude = str(document.get("x", "")).strip()
            latitude = str(document.get("y", "")).strip()
            if not longitude or not latitude:
                continue

            region = await client.coord_to_region(longitude, latitude, region_type="H")
            if region is None:
                region = await client.coord_to_region(
                    longitude, latitude, region_type="B"
                )
            if region is None:
                continue

            region_code = self._map_region_to_code(region)
            if region_code is None:
                continue

            dong = str(region.get("region_3depth_name", "")).strip()
            if not dong:
                continue

            station_name = (
                str(document.get("place_name") or station_query).strip()
                or station_query
            )
            candidate_key = (station_name, region_code, dong)
            if candidate_key in seen_candidates:
                continue
            seen_candidates.add(candidate_key)
            candidates.append(
                {
                    "station_name": station_name,
                    "region_code": region_code,
                    "dong": dong,
                    "label": self._build_label(region),
                }
            )

        return candidates

    def _map_region_to_code(self, region: Mapping[str, object]) -> str | None:
        sido = str(region.get("region_1depth_name", "")).strip()
        sigungu = str(region.get("region_2depth_name", "")).strip()
        if sido and sigungu:
            normalized_name = _normalize_region_name(f"{sido} {sigungu}")
            mapped_code = _NORMALIZED_REGION_NAME_TO_CODE.get(normalized_name)
            if mapped_code:
                return mapped_code

        raw_code = str(region.get("code", "")).strip()
        if raw_code:
            maybe_region_code = raw_code[:5]
            if is_valid_region_code(maybe_region_code):
                return maybe_region_code
        return None

    def _build_label(self, region: Mapping[str, object]) -> str:
        label_parts = [
            str(region.get("region_1depth_name", "")).strip(),
            str(region.get("region_2depth_name", "")).strip(),
            str(region.get("region_3depth_name", "")).strip(),
        ]
        return " ".join(part for part in label_parts if part)


class StationLookupClient(Protocol):
    async def search_keyword(
        self, query: str, *, category_group_code: str = "SW8"
    ) -> list[dict[str, object]]: ...

    async def coord_to_region(
        self, longitude: str, latitude: str, *, region_type: str = "H"
    ) -> dict[str, object] | None: ...
