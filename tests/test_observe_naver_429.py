from __future__ import annotations

import importlib

import pytest

observer = importlib.import_module("scripts.observe_naver_429")

pytestmark = pytest.mark.anyio


class DummyResponse:
    status_code: int
    headers: dict[str, str]

    def __init__(self, status_code: int, headers: dict[str, str] | None = None) -> None:
        self.status_code = status_code
        self.headers = headers or {}


async def test_run_fails_immediately_on_first_429() -> None:
    seen_calls: list[dict[str, str]] = []

    async def fake_request(
        *,
        region_code: str,
        property_type: str,
        trade_type: str,
        request_index: int,
    ) -> DummyResponse:
        _ = trade_type
        _ = request_index
        seen_calls.append(
            {
                "region_code": region_code,
                "property_type": property_type,
            }
        )
        return DummyResponse(
            429,
            headers={"Retry-After": "7", "X-RateLimit-Remaining": "0"},
        )

    args = observer.CliArgs(
        region_codes=["11680"],
        property_types=["APT"],
        max_regions=1,
        requests_per_region=3,
        timeout_seconds=5.0,
        fingerprint="stage6-observe-test",
    )
    report = await observer._run(args, request_fn=fake_request)
    assert report["status"] == "rate_limited"
    assert report["result"] == "failure"
    assert len(seen_calls) == 1
    assert report["first_429"]["retry_after"] == "7"


async def test_run_succeeds_when_no_429() -> None:
    async def fake_request(
        *,
        region_code: str,
        property_type: str,
        trade_type: str,
        request_index: int,
    ) -> DummyResponse:
        _ = region_code
        _ = property_type
        _ = trade_type
        _ = request_index
        return DummyResponse(200, headers={})

    args = observer.CliArgs(
        region_codes=["11680"],
        property_types=["APT"],
        max_regions=1,
        requests_per_region=2,
        timeout_seconds=5.0,
        fingerprint="stage6-observe-test",
    )
    report = await observer._run(args, request_fn=fake_request)
    assert report["status"] == "ok"
    assert report["result"] == "success"
    assert report["first_429"] is None


async def test_run_reports_error_on_unexpected_exception() -> None:
    async def fake_request(
        *,
        region_code: str,
        property_type: str,
        trade_type: str,
        request_index: int,
    ) -> DummyResponse:
        _ = region_code
        _ = property_type
        _ = trade_type
        _ = request_index
        raise RuntimeError("network down")

    args = observer.CliArgs(
        region_codes=["11680"],
        property_types=["APT"],
        max_regions=1,
        requests_per_region=1,
        timeout_seconds=5.0,
        fingerprint="stage6-observe-test",
    )
    report = await observer._run(args, request_fn=fake_request)
    assert report["status"] == "error"
    assert report["result"] == "failure"
    assert report["error_type"] == "RuntimeError"


async def test_run_reports_error_on_non_429_http_status() -> None:
    seen_calls: list[int] = []

    async def fake_request(
        *,
        region_code: str,
        property_type: str,
        trade_type: str,
        request_index: int,
    ) -> DummyResponse:
        _ = region_code
        _ = property_type
        _ = trade_type
        seen_calls.append(request_index)
        return DummyResponse(500, headers={})

    args = observer.CliArgs(
        region_codes=["11680"],
        property_types=["APT"],
        max_regions=1,
        requests_per_region=3,
        timeout_seconds=5.0,
        fingerprint="stage6-observe-test",
    )
    report = await observer._run(args, request_fn=fake_request)

    assert report["status"] == "error"
    assert report["result"] == "failure"
    assert "reason" in report
    assert seen_calls == [1]


async def test_rate_limited_report_contains_context_and_headers() -> None:
    async def fake_request(
        *,
        region_code: str,
        property_type: str,
        trade_type: str,
        request_index: int,
    ) -> DummyResponse:
        _ = region_code
        _ = property_type
        _ = trade_type
        _ = request_index
        return DummyResponse(
            429,
            headers={
                "Retry-After": "7",
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": "1739836800",
                "X-Extra": "ignored",
            },
        )

    args = observer.CliArgs(
        region_codes=["11680"],
        property_types=["APT"],
        max_regions=1,
        requests_per_region=3,
        timeout_seconds=5.0,
        fingerprint="stage6-observe-test",
    )
    report = await observer._run(args, request_fn=fake_request)

    assert report["status"] == "rate_limited"
    assert report["fingerprint"] == "stage6-observe-test"
    assert report["executed_at"]
    assert report["action_hint"]

    summary = report["summary"]
    assert summary["attempted_requests"] == 1
    assert summary["regions_attempted"] == ["11680"]
    assert summary["first_429_at_request_index"] == 1

    first_429 = report["first_429"]
    assert first_429["region_code"] == "11680"
    assert first_429["property_type"] == "APT"
    assert first_429["request_index"] == 1
    assert first_429["response_headers_subset"] == {
        "retry-after": "7",
        "x-ratelimit-remaining": "0",
        "x-ratelimit-reset": "1739836800",
    }


async def test_invalid_cli_values_raise_parser_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "observe_naver_429.py",
            "--max-regions",
            "0",
            "--requests-per-region",
            "0",
            "--timeout-seconds",
            "0",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        observer._parse_args()

    assert exc_info.value.code == 2
