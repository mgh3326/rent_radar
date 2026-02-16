from __future__ import annotations

import importlib
from contextlib import asynccontextmanager
from typing import cast

import pytest

from src.crawlers.base import CrawlResult

live_data = importlib.import_module("scripts.manual_prepare_mcp_live_data")

pytestmark = pytest.mark.anyio


async def test_parse_args_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sys.argv",
        ["manual_prepare_mcp_live_data.py"],
    )

    args = live_data._parse_args()

    assert args.region_codes == "41135"
    assert args.property_types == "아파트"
    assert args.max_regions == 1


@pytest.mark.anyio
async def test_run_reports_success_with_upserted_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = live_data.CliArgs(
        region_codes="41135",
        property_types="아파트",
        max_regions=1,
    )

    @asynccontextmanager
    async def fake_session_context():
        yield object()

    class FakeCrawler:
        def __init__(
            self,
            *,
            region_names: list[str],
            property_types: list[str],
            **_kwargs: object,
        ) -> None:
            assert region_names == ["성남시분당구"]
            assert property_types == ["아파트"]
            self.last_run_metrics: dict[str, object] = {"retry_count": 1}

        async def run(self) -> CrawlResult[object]:
            return CrawlResult(count=2, rows=[object(), object()], errors=[])

    async def fake_upsert_listings(_session: object, rows: list[object]) -> int:
        assert len(rows) == 2
        return 2

    monkeypatch.setattr(
        "scripts.manual_prepare_mcp_live_data.region_codes_to_district_names",
        lambda _codes: ["성남시분당구"],
    )
    monkeypatch.setattr(
        "scripts.manual_prepare_mcp_live_data.ZigbangCrawler",
        FakeCrawler,
    )
    monkeypatch.setattr(
        "scripts.manual_prepare_mcp_live_data.session_context",
        fake_session_context,
    )
    monkeypatch.setattr(
        "scripts.manual_prepare_mcp_live_data.upsert_listings",
        fake_upsert_listings,
    )

    report = await live_data._run(args)

    assert report["status"] == "success"
    assert cast(dict[str, object], report["persistence"])["upsert_count"] == 2


@pytest.mark.anyio
async def test_run_reports_failure_when_no_rows_persisted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = live_data.CliArgs(
        region_codes="41135",
        property_types="아파트",
        max_regions=1,
    )

    @asynccontextmanager
    async def fake_session_context():
        yield object()

    class FakeCrawler:
        def __init__(
            self,
            *,
            region_names: list[str],
            property_types: list[str],
            **_kwargs: object,
        ) -> None:
            assert region_names == ["성남시분당구"]
            assert property_types == ["아파트"]
            self.last_run_metrics: dict[str, object] = {"retry_count": 3}

        async def run(self) -> CrawlResult[object]:
            return CrawlResult(count=0, rows=[], errors=[])

    async def fake_upsert_listings(_session: object, _rows: list[object]) -> int:
        return 0

    monkeypatch.setattr(
        "scripts.manual_prepare_mcp_live_data.region_codes_to_district_names",
        lambda _codes: ["성남시분당구"],
    )
    monkeypatch.setattr(
        "scripts.manual_prepare_mcp_live_data.ZigbangCrawler",
        FakeCrawler,
    )
    monkeypatch.setattr(
        "scripts.manual_prepare_mcp_live_data.session_context",
        fake_session_context,
    )
    monkeypatch.setattr(
        "scripts.manual_prepare_mcp_live_data.upsert_listings",
        fake_upsert_listings,
    )

    report = await live_data._run(args)

    assert report["status"] == "failure"
    assert "upsert_count <= 0" in cast(list[object], report["failures"])
