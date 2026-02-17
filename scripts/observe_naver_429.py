from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, cast

import httpx

BASE_URL: Final = "https://new.land.naver.com/api"
TRADE_TYPES: Final[tuple[str, ...]] = ("B1", "B2")


@dataclass(frozen=True)
class CliArgs:
    region_codes: list[str]
    property_types: list[str]
    max_regions: int
    requests_per_region: int
    timeout_seconds: float
    fingerprint: str


RequestFn = Callable[..., Awaitable[object]]


def _split_csv(raw_value: str) -> list[str]:
    return [part.strip() for part in raw_value.split(",") if part.strip()]


def _parse_args() -> CliArgs:
    parser = argparse.ArgumentParser(
        description="Run fail-fast local observer for Naver 429 responses."
    )
    _ = parser.add_argument(
        "--region-codes",
        default="11680",
        help="Comma-separated region codes (default: 11680).",
    )
    _ = parser.add_argument(
        "--property-types",
        default="APT",
        help="Comma-separated property types (default: APT).",
    )
    _ = parser.add_argument(
        "--max-regions",
        type=int,
        default=1,
        help="Maximum region count to probe (default: 1).",
    )
    _ = parser.add_argument(
        "--requests-per-region",
        type=int,
        default=5,
        help="Requests per region/property/trade combination (default: 5).",
    )
    _ = parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=5.0,
        help="HTTP timeout seconds (default: 5.0).",
    )
    _ = parser.add_argument(
        "--fingerprint",
        default="stage6-observe-local",
        help="Evidence fingerprint string (default: stage6-observe-local).",
    )

    parsed = parser.parse_args()
    region_codes = _split_csv(cast(str, parsed.region_codes))
    property_types = _split_csv(cast(str, parsed.property_types))
    max_regions = cast(int, parsed.max_regions)
    requests_per_region = cast(int, parsed.requests_per_region)
    timeout_seconds = cast(float, parsed.timeout_seconds)
    fingerprint = cast(str, parsed.fingerprint)

    if not region_codes:
        parser.error("--region-codes must include at least one region code")
    if not property_types:
        parser.error("--property-types must include at least one property type")
    if max_regions <= 0:
        parser.error("--max-regions must be > 0")
    if requests_per_region <= 0:
        parser.error("--requests-per-region must be > 0")
    if timeout_seconds <= 0:
        parser.error("--timeout-seconds must be > 0")

    return CliArgs(
        region_codes=region_codes,
        property_types=property_types,
        max_regions=max_regions,
        requests_per_region=requests_per_region,
        timeout_seconds=timeout_seconds,
        fingerprint=fingerprint,
    )


async def _request_articles_once(
    *,
    client: httpx.AsyncClient,
    region_code: str,
    property_type: str,
    trade_type: str,
) -> httpx.Response:
    return await client.get(
        f"{BASE_URL}/articles",
        params={
            "cortarNo": region_code,
            "realEstateType": property_type,
            "tradeType": trade_type,
        },
    )


def _extract_rate_limit_headers(headers: Mapping[str, str]) -> dict[str, str]:
    lowered_headers = {str(key).lower(): str(value) for key, value in headers.items()}
    selected: dict[str, str] = {}
    for key in ("retry-after", "x-ratelimit-remaining", "x-ratelimit-reset"):
        value = lowered_headers.get(key)
        if value is not None:
            selected[key] = value
    return selected


def _build_action_hint(status: str) -> str:
    if status == "ok":
        return "No HTTP 429 observed in configured probe scope."
    if status == "rate_limited":
        return "HTTP 429 captured. Preserve this JSON as Stage 6 phase-1 evidence."
    if status == "error":
        return "Unexpected observer error. Inspect error_type/reason and rerun with narrow scope."
    return "Unknown observer status. Inspect report contract."


def _build_report(
    *,
    args: CliArgs,
    executed_at: str,
    status: str,
    result: str,
    attempted_requests: int,
    regions_attempted: list[str],
    first_429: dict[str, object] | None,
    reason: str | None = None,
    error_type: str | None = None,
) -> dict[str, object]:
    report: dict[str, object] = {
        "executed_at": executed_at,
        "fingerprint": args.fingerprint,
        "status": status,
        "result": result,
        "summary": {
            "attempted_requests": attempted_requests,
            "regions_attempted": regions_attempted,
            "first_429_at_request_index": (
                first_429["request_index"] if first_429 is not None else None
            ),
        },
        "first_429": first_429,
        "action_hint": _build_action_hint(status),
    }
    if reason is not None:
        report["reason"] = reason
    if error_type is not None:
        report["error_type"] = error_type
    return report


async def _run_with_request_fn(
    args: CliArgs, request_fn: RequestFn
) -> dict[str, object]:
    executed_at = datetime.now(UTC).isoformat()
    request_index = 0
    regions = args.region_codes[: args.max_regions]
    regions_attempted: list[str] = []
    seen_regions: set[str] = set()

    try:
        for region_code in regions:
            if region_code not in seen_regions:
                seen_regions.add(region_code)
                regions_attempted.append(region_code)

            for property_type in args.property_types:
                for trade_type in TRADE_TYPES:
                    for _ in range(args.requests_per_region):
                        request_index += 1
                        response = await request_fn(
                            region_code=region_code,
                            property_type=property_type,
                            trade_type=trade_type,
                            request_index=request_index,
                        )

                        status_code = int(getattr(response, "status_code", 0))
                        if status_code == 429:
                            headers_obj = getattr(response, "headers", {})
                            headers = cast(Mapping[str, str], headers_obj)
                            headers_subset = _extract_rate_limit_headers(headers)
                            first_429: dict[str, object] = {
                                "region_code": region_code,
                                "property_type": property_type,
                                "trade_type": trade_type,
                                "request_index": request_index,
                                "response_headers_subset": headers_subset,
                                "retry_after": headers_subset.get("retry-after"),
                            }
                            return _build_report(
                                args=args,
                                executed_at=executed_at,
                                status="rate_limited",
                                result="failure",
                                attempted_requests=request_index,
                                regions_attempted=regions_attempted,
                                first_429=first_429,
                            )

        return _build_report(
            args=args,
            executed_at=executed_at,
            status="ok",
            result="success",
            attempted_requests=request_index,
            regions_attempted=regions_attempted,
            first_429=None,
        )
    except Exception as exc:  # noqa: BLE001
        return _build_report(
            args=args,
            executed_at=executed_at,
            status="error",
            result="failure",
            attempted_requests=request_index,
            regions_attempted=regions_attempted,
            first_429=None,
            reason=str(exc),
            error_type=type(exc).__name__,
        )


async def _run(args: CliArgs, request_fn: RequestFn | None = None) -> dict[str, object]:
    if request_fn is not None:
        return await _run_with_request_fn(args, request_fn)

    timeout = httpx.Timeout(args.timeout_seconds)
    async with httpx.AsyncClient(timeout=timeout) as client:

        async def client_request_fn(**kwargs: object) -> object:
            return await _request_articles_once(
                client=client,
                region_code=str(kwargs["region_code"]),
                property_type=str(kwargs["property_type"]),
                trade_type=str(kwargs["trade_type"]),
            )

        return await _run_with_request_fn(args, client_request_fn)


async def _async_main() -> int:
    args = _parse_args()
    report = await _run(args)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["status"] == "ok":
        return 0
    if report["status"] == "rate_limited":
        return 1
    return 2


def main() -> None:
    raise SystemExit(asyncio.run(_async_main()))


if __name__ == "__main__":
    main()
