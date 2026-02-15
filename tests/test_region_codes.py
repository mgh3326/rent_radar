from __future__ import annotations

import pytest

from src.config.region_codes import region_code_to_parts, region_code_to_sigungu_names


pytestmark = pytest.mark.anyio


async def test_region_code_to_sigungu_names_returns_candidates_for_compound_name() -> (
    None
):
    names = region_code_to_sigungu_names("41135")

    assert names[0] == "성남시분당구"
    assert "분당구" in names


async def test_region_code_to_sigungu_names_returns_empty_for_invalid_code() -> None:
    assert region_code_to_sigungu_names("99999") == []


async def test_region_code_to_parts_returns_compound_sigungu_and_aliases() -> None:
    parts = region_code_to_parts("41135")

    assert parts is not None
    assert parts["sido"] == "경기도"
    assert parts["sigungu"] == "성남시분당구"
    assert parts["aliases"] == ["성남시분당구", "분당구"]


async def test_region_code_to_parts_returns_simple_sigungu_alias() -> None:
    parts = region_code_to_parts("11110")

    assert parts is not None
    assert parts["sido"] == "서울특별시"
    assert parts["sigungu"] == "종로구"
    assert parts["aliases"] == ["종로구"]


async def test_region_code_to_parts_returns_none_for_invalid_code() -> None:
    assert region_code_to_parts("99999") is None
