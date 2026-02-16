# ruff: noqa: E402

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.crawlers.zigbang import ZigbangSchemaMismatchError
from src.taskiq_app.tasks import crawl_zigbang_listings


@dataclass(frozen=True)
class CliArgs:
    fingerprint: str = "manual-smoke"
    allow_duplicate_run: bool = False


def _parse_args() -> CliArgs:
    parser = argparse.ArgumentParser(
        description="Run local smoke for crawl_zigbang_listings with stable status contract."
    )
    parser.add_argument(
        "--fingerprint",
        default="manual-smoke",
        help="Evidence identifier stored in the smoke report (default: manual-smoke).",
    )
    parser.add_argument(
        "--allow-duplicate-run",
        action="store_true",
        help="Treat skipped_duplicate_execution as success.",
    )

    parsed = parser.parse_args()
    return CliArgs(
        fingerprint=str(parsed.fingerprint),
        allow_duplicate_run=bool(parsed.allow_duplicate_run),
    )


def _build_action_hint(status: str, *, allow_duplicate_run: bool) -> str:
    if status == "ok":
        return "No action required."
    if status == "schema_mismatch":
        return "Fail-fast crawler behavior is preserved; inspect schema samples and update parser/fixture before retrying."
    if status == "skipped_duplicate_execution":
        if allow_duplicate_run:
            return "Dedup lock prevented execution; rerun after dedup TTL if you need fresh crawl evidence."
        return "Execution dedup lock blocked this run; rerun later or pass --allow-duplicate-run when lock collision is acceptable."
    if status == "unexpected_exception":
        return "Inspect traceback/logs and resolve runtime error before retrying live smoke."
    return "Unexpected task status; inspect raw result and update smoke status mapping if this is an intentional new contract."


def _normalize_result(status: str, *, allow_duplicate_run: bool) -> str:
    if status in {"ok", "schema_mismatch"}:
        return "success"
    if status == "skipped_duplicate_execution" and allow_duplicate_run:
        return "success"
    return "failure"


async def _run(args: CliArgs) -> dict[str, object]:
    base_report: dict[str, object] = {
        "source": "zigbang",
        "fingerprint": args.fingerprint,
        "allow_duplicate_run": args.allow_duplicate_run,
        "executed_at": datetime.now(UTC).isoformat(),
    }

    try:
        task_fn = cast(Any, crawl_zigbang_listings)
        raw_result = await task_fn.original_func()
        if not isinstance(raw_result, dict):
            status = "unexpected_payload"
            normalized: dict[str, object] = {
                "raw_result_type": type(raw_result).__name__,
            }
        else:
            status = str(raw_result.get("status", "unknown"))
            normalized = raw_result

        result = _normalize_result(status, allow_duplicate_run=args.allow_duplicate_run)
        report = {
            **base_report,
            "status": status,
            "result": result,
            "action_hint": _build_action_hint(
                status, allow_duplicate_run=args.allow_duplicate_run
            ),
            "task_result": normalized,
        }
        return report
    except ZigbangSchemaMismatchError as exc:
        status = "schema_mismatch"
        return {
            **base_report,
            "status": status,
            "result": "success",
            "reason": str(exc),
            "action_hint": _build_action_hint(
                status, allow_duplicate_run=args.allow_duplicate_run
            ),
        }
    except Exception as exc:  # noqa: BLE001
        status = "unexpected_exception"
        return {
            **base_report,
            "status": status,
            "result": "failure",
            "reason": str(exc),
            "error_type": type(exc).__name__,
            "action_hint": _build_action_hint(
                status, allow_duplicate_run=args.allow_duplicate_run
            ),
        }


async def _async_main() -> int:
    logging.disable(logging.CRITICAL)
    args = _parse_args()
    report = await _run(args)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("result") == "success" else 1


def main() -> None:
    raise SystemExit(asyncio.run(_async_main()))


if __name__ == "__main__":
    main()
