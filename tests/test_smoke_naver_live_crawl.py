from __future__ import annotations

import importlib

import pytest

smoke = importlib.import_module("scripts.smoke_naver_live_crawl")

pytestmark = pytest.mark.anyio


async def test_smoke_reports_success_only_when_inserted_positive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_original_func() -> dict[str, object]:
        return {
            "source": "naver",
            "status": "ok",
            "count": 3,
            "fetched": 5,
        }

    monkeypatch.setattr(smoke.crawl_naver_listings, "original_func", fake_original_func)

    report = await smoke._run(smoke.CliArgs(fingerprint="stage6-phase2-test"))

    assert report["source"] == "naver"
    assert report["status"] == "ok"
    assert report["result"] == "success"


async def test_smoke_reports_failure_on_error_or_zero_inserted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_original_func_zero() -> dict[str, object]:
        return {
            "source": "naver",
            "status": "ok",
            "count": 0,
            "fetched": 5,
        }

    monkeypatch.setattr(
        smoke.crawl_naver_listings,
        "original_func",
        fake_original_func_zero,
    )
    zero_report = await smoke._run(smoke.CliArgs(fingerprint="stage6-phase2-test"))
    assert zero_report["result"] == "failure"

    async def fake_original_func_error() -> dict[str, object]:
        return {
            "source": "naver",
            "status": "error",
            "count": 0,
            "reason": "HTTP 429 exhausted retries",
        }

    monkeypatch.setattr(
        smoke.crawl_naver_listings,
        "original_func",
        fake_original_func_error,
    )
    error_report = await smoke._run(smoke.CliArgs(fingerprint="stage6-phase2-test"))
    assert error_report["status"] == "error"
    assert error_report["result"] == "failure"
