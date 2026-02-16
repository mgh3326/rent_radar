from __future__ import annotations

import importlib

import pytest

from src.crawlers.zigbang import ZigbangSchemaMismatchError

smoke = importlib.import_module("scripts.smoke_zigbang_live_crawl")

pytestmark = pytest.mark.anyio


async def test_run_reports_success_when_task_status_ok(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_original_func() -> dict[str, object]:
        return {
            "source": "zigbang",
            "status": "ok",
            "fetched": 3,
            "count": 2,
            "deactivated": 1,
        }

    monkeypatch.setattr(
        smoke.crawl_zigbang_listings, "original_func", fake_original_func
    )

    report = await smoke._run(
        smoke.CliArgs(fingerprint="manual-smoke", allow_duplicate_run=False)
    )

    assert report["status"] == "ok"
    assert report["result"] == "success"
    assert "action_hint" in report


async def test_run_reports_success_when_schema_mismatch_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_original_func() -> dict[str, object]:
        raise ZigbangSchemaMismatchError("raw_count=10 parsed_count=0")

    monkeypatch.setattr(
        smoke.crawl_zigbang_listings, "original_func", fake_original_func
    )

    report = await smoke._run(
        smoke.CliArgs(fingerprint="manual-smoke", allow_duplicate_run=False)
    )

    assert report["status"] == "schema_mismatch"
    assert report["result"] == "success"
    assert "action_hint" in report


async def test_run_reports_failure_when_skipped_duplicate_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_original_func() -> dict[str, object]:
        return {
            "source": "zigbang",
            "status": "skipped_duplicate_execution",
            "count": 0,
        }

    monkeypatch.setattr(
        smoke.crawl_zigbang_listings, "original_func", fake_original_func
    )

    report = await smoke._run(
        smoke.CliArgs(fingerprint="manual-smoke", allow_duplicate_run=False)
    )

    assert report["status"] == "skipped_duplicate_execution"
    assert report["result"] == "failure"
    assert "action_hint" in report


async def test_run_reports_failure_on_unexpected_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_original_func() -> dict[str, object]:
        raise RuntimeError("unexpected boom")

    monkeypatch.setattr(
        smoke.crawl_zigbang_listings, "original_func", fake_original_func
    )

    report = await smoke._run(
        smoke.CliArgs(fingerprint="manual-smoke", allow_duplicate_run=False)
    )

    assert report["status"] == "unexpected_exception"
    assert report["result"] == "failure"
    assert "action_hint" in report
