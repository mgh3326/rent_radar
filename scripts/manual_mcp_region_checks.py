from __future__ import annotations

# ruff: noqa: E402

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.config.region_codes import REGION_CODE_TO_NAME, region_code_to_parts
from src.mcp_server.server import mcp

_CHECK_REGION_CODES = ("41135", "11680", "11110")


@dataclass(frozen=True)
class CliArgs:
    limit: int


def _parse_args() -> CliArgs:
    parser = argparse.ArgumentParser(
        description="Manual MCP checks for region filtering behavior."
    )
    _ = parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="search_rent result limit for manual checks (default: 20)",
    )
    namespace = parser.parse_args()
    return CliArgs(limit=cast(int, namespace.limit))


def _normalize_payload(mapping: dict[object, object]) -> dict[str, object]:
    return {str(key): value for key, value in mapping.items()}


def _extract_payload(tool_result: object) -> dict[str, object]:
    if isinstance(tool_result, dict):
        return _normalize_payload(tool_result)
    if isinstance(tool_result, tuple):
        for part in tool_result:
            if isinstance(part, dict):
                return _normalize_payload(part)
            if isinstance(part, list) and part:
                maybe_text = getattr(part[0], "text", None)
                if isinstance(maybe_text, str):
                    loaded = json.loads(maybe_text)
                    if isinstance(loaded, dict):
                        return _normalize_payload(loaded)
    raise RuntimeError("Failed to extract structured MCP payload")


def _extract_regions(payload: dict[str, object]) -> list[dict[str, object]]:
    regions_raw = payload.get("regions")
    if not isinstance(regions_raw, list):
        raise RuntimeError("MCP list_regions payload has no list `regions`")
    regions: list[dict[str, object]] = []
    for item in regions_raw:
        if not isinstance(item, dict):
            raise RuntimeError("MCP list_regions payload includes non-dict item")
        regions.append(_normalize_payload(item))
    return regions


def _extract_items(payload: dict[str, object]) -> list[dict[str, object]]:
    items_raw = payload.get("items")
    if not isinstance(items_raw, list):
        raise RuntimeError("MCP search_rent payload has no list `items`")
    items: list[dict[str, object]] = []
    for item in items_raw:
        if not isinstance(item, dict):
            raise RuntimeError("MCP search_rent payload includes non-dict item")
        items.append(_normalize_payload(item))
    return items


async def _preflight_tools() -> None:
    required = {"list_regions", "search_rent"}
    tools = await mcp.list_tools()
    tool_names = {getattr(tool, "name", None) for tool in tools}
    missing = sorted(name for name in required if name not in tool_names)
    if missing:
        joined = ", ".join(missing)
        raise RuntimeError(f"Required MCP tools are missing: {joined}")


def _make_check(name: str, ok: bool, details: dict[str, object]) -> dict[str, object]:
    return {"name": name, "ok": ok, "details": details}


def _build_region_diagnostics() -> dict[str, object]:
    diagnostics: dict[str, object] = {}
    for code in _CHECK_REGION_CODES:
        diagnostics[code] = {
            "canonical_name": REGION_CODE_TO_NAME.get(code),
            "parts": region_code_to_parts(code),
        }
    return diagnostics


async def _run(args: CliArgs) -> dict[str, object]:
    failures: list[str] = []
    checks: list[dict[str, object]] = []

    if args.limit <= 0:
        raise RuntimeError("--limit must be greater than 0")

    await _preflight_tools()

    regions_payload = _extract_payload(
        await mcp.call_tool("list_regions", {"sido": "경기도", "sigungu": "분당구"})
    )
    regions = _extract_regions(regions_payload)
    regions_ok = (
        len(regions) > 0
        and any(region.get("sigungu") == "성남시분당구" for region in regions)
        and all(region.get("sido") == "경기도" for region in regions)
        and all("분당구" in str(region.get("sigungu", "")) for region in regions)
    )
    checks.append(
        _make_check(
            "list_regions(경기도, 분당구)",
            regions_ok,
            {
                "count": len(regions),
                "sample": regions[:5],
            },
        )
    )
    if not regions_ok:
        failures.append("list_regions_partial_match_failed")

    search_41135_payload = _extract_payload(
        await mcp.call_tool(
            "search_rent",
            {"region_code": "41135", "property_type": "apt", "limit": args.limit},
        )
    )
    search_41135_items = _extract_items(search_41135_payload)
    search_41135_ok = (
        len(search_41135_items) > 0
        and all(item.get("property_type") == "apt" for item in search_41135_items)
        and any("분당구" in str(item.get("dong", "")) for item in search_41135_items)
    )
    checks.append(
        _make_check(
            "search_rent(region_code=41135, property_type=apt)",
            search_41135_ok,
            {
                "count": len(search_41135_items),
                "sample": search_41135_items[:5],
            },
        )
    )
    if not search_41135_ok:
        failures.append("search_rent_41135_failed")

    search_11680_payload = _extract_payload(
        await mcp.call_tool(
            "search_rent",
            {"region_code": "11680", "property_type": "apt", "limit": args.limit},
        )
    )
    search_11680_items = _extract_items(search_11680_payload)
    search_11680_ok = (
        len(search_11680_items) > 0
        and all(item.get("property_type") == "apt" for item in search_11680_items)
        and any(
            "강남구" in str(item.get("address", ""))
            or str(item.get("dong", "")) == "강남구"
            for item in search_11680_items
        )
    )
    checks.append(
        _make_check(
            "search_rent(region_code=11680, property_type=apt)",
            search_11680_ok,
            {
                "count": len(search_11680_items),
                "sample": search_11680_items[:5],
            },
        )
    )
    if not search_11680_ok:
        failures.append("search_rent_11680_failed")

    search_11110_payload = _extract_payload(
        await mcp.call_tool(
            "search_rent",
            {"region_code": "11110", "property_type": "apt", "limit": args.limit},
        )
    )
    search_11110_items = _extract_items(search_11110_payload)
    search_11110_ok = (
        len(search_11110_items) > 0
        and all(item.get("property_type") == "apt" for item in search_11110_items)
        and any(
            "종로구" in str(item.get("address", ""))
            or "종로구" in str(item.get("dong", ""))
            for item in search_11110_items
        )
    )
    checks.append(
        _make_check(
            "search_rent(region_code=11110, property_type=apt)",
            search_11110_ok,
            {
                "count": len(search_11110_items),
                "sample": search_11110_items[:5],
            },
        )
    )
    if not search_11110_ok:
        failures.append("search_rent_11110_failed")

    report: dict[str, object] = {
        "status": "success" if not failures else "failure",
        "executed_at": datetime.now(UTC).isoformat(),
        "region_code_diagnostics": _build_region_diagnostics(),
        "checks": checks,
    }
    if failures:
        report["failures"] = failures
    return report


async def _async_main() -> int:
    args = _parse_args()
    try:
        report = await _run(args)
    except Exception as exc:  # noqa: BLE001
        error_report = {
            "status": "failure",
            "executed_at": datetime.now(UTC).isoformat(),
            "checks": [],
            "failures": [str(exc)],
        }
        print(json.dumps(error_report, ensure_ascii=False, indent=2))
        return 1

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("status") == "success" else 1


def main() -> None:
    raise SystemExit(asyncio.run(_async_main()))


if __name__ == "__main__":
    main()
