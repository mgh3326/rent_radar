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

from src.taskiq_app.tasks import crawl_naver_listings


@dataclass(frozen=True)
class CliArgs:
    fingerprint: str = "stage6-phase2-smoke"


def _parse_args() -> CliArgs:
    parser = argparse.ArgumentParser(
        description="Run local smoke for crawl_naver_listings with Stage 6 contract."
    )
    parser.add_argument(
        "--fingerprint",
        default="stage6-phase2-smoke",
        help="Evidence identifier included in the smoke report.",
    )
    parsed = parser.parse_args()
    return CliArgs(fingerprint=str(parsed.fingerprint))


def _to_int(value: object, default: int = 0) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    text = str(value).replace(",", "").strip()
    if not text:
        return default
    if text.isdigit():
        return int(text)
    return default


async def _run(args: CliArgs) -> dict[str, object]:
    base_report: dict[str, object] = {
        "source": "naver",
        "fingerprint": args.fingerprint,
        "executed_at": datetime.now(UTC).isoformat(),
    }

    try:
        task_fn = cast(Any, crawl_naver_listings)
        raw_result = await task_fn.original_func()

        if isinstance(raw_result, dict):
            status = str(raw_result.get("status", "unknown"))
            inserted = _to_int(raw_result.get("count", 0), 0)
            task_result: dict[str, object] = raw_result
        else:
            status = "unexpected_payload"
            inserted = 0
            task_result = {"raw_result_type": type(raw_result).__name__}

        result = "success" if status == "ok" and inserted > 0 else "failure"
        return {
            **base_report,
            "status": status,
            "result": result,
            "task_result": task_result,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            **base_report,
            "status": "error",
            "result": "failure",
            "reason": str(exc),
            "error_type": type(exc).__name__,
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
