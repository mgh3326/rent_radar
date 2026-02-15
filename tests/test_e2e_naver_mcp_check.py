from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from typing import cast

import pytest

from scripts import e2e_naver_mcp_check as naver_check


def _make_args(mcp_limit: int) -> naver_check.CliArgs:
    return naver_check.CliArgs(
        seed_source="naver_test_seed",
        seed_dong_prefix="NAVER_MCP_TEST",
        mcp_limit=mcp_limit,
        cleanup_scope="source_only",
    )


def _build_items(*, source: str, dong: str, limit: int) -> list[dict[str, object]]:
    items: list[dict[str, object]] = [
        {
            "id": 1,
            "source": source,
            "source_id": "seed-1",
            "dong": dong,
        },
        {
            "id": 2,
            "source": source,
            "source_id": "seed-2",
            "dong": dong,
        },
        {
            "id": 3,
            "source": source,
            "source_id": "seed-3",
            "dong": dong,
        },
    ]
    return items[:limit]


def _require_dict(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    raw = cast(dict[object, object], value)
    normalized: dict[str, object] = {}
    for key, item in raw.items():
        normalized[str(key)] = item
    return normalized


def _extract_limit_and_dong(query: dict[str, object]) -> tuple[int, str]:
    limit_raw = query.get("limit")
    dong_raw = query.get("dong")
    assert isinstance(limit_raw, int)
    assert isinstance(dong_raw, str)
    return limit_raw, dong_raw


async def _run_script(args: naver_check.CliArgs) -> dict[str, object]:
    run_impl = cast(
        Callable[[naver_check.CliArgs], Awaitable[dict[str, object]]],
        getattr(naver_check, "_run"),
    )
    return await run_impl(args)


def _patch_run_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    *,
    expected_seed_source: str,
    upsert_count: int,
    observed_seed_row_count: int,
    expected_seed_rows_len: int = 3,
    payload_builder: Callable[[int, dict[str, object]], dict[str, object]],
) -> None:
    @asynccontextmanager
    async def fake_session_context():
        yield object()

    async def fake_cleanup_seed_source(
        _session: object, seed_source: str
    ) -> dict[str, int]:
        assert seed_source == expected_seed_source
        return {
            "seed_listing_ids_count": 0,
            "favorites_deleted": 0,
            "price_changes_deleted": 0,
            "listings_deleted": 0,
            "remaining_source_count": 0,
        }

    async def fake_upsert_listings(
        _session: object,
        seed_rows: list[object],
    ) -> int:
        assert len(seed_rows) == expected_seed_rows_len
        return upsert_count

    async def fake_count_seed_rows(
        _session: object,
        *,
        seed_source: str,
        seed_dong: str,
    ) -> int:
        assert seed_source == expected_seed_source
        assert seed_dong
        return observed_seed_row_count

    call_index = {"value": 0}

    async def fake_call_tool(
        tool_name: str,
        query: dict[str, object],
    ) -> dict[str, object]:
        assert tool_name == "search_rent"
        call_index["value"] += 1
        return payload_builder(call_index["value"], query)

    monkeypatch.setattr(
        "scripts.e2e_naver_mcp_check.session_context", fake_session_context
    )
    monkeypatch.setattr(
        "scripts.e2e_naver_mcp_check._cleanup_seed_source",
        fake_cleanup_seed_source,
    )
    monkeypatch.setattr(
        "scripts.e2e_naver_mcp_check.upsert_listings", fake_upsert_listings
    )
    monkeypatch.setattr(
        "scripts.e2e_naver_mcp_check._count_seed_rows", fake_count_seed_rows
    )
    monkeypatch.setattr("scripts.e2e_naver_mcp_check.mcp.call_tool", fake_call_tool)


@pytest.mark.anyio
async def test_run_success_limit_three(monkeypatch: pytest.MonkeyPatch) -> None:
    args = _make_args(3)

    def payload_builder(
        call_number: int, query: dict[str, object]
    ) -> dict[str, object]:
        limit, dong = _extract_limit_and_dong(query)
        items = _build_items(source=args.seed_source, dong=dong, limit=limit)
        return {
            "count": len(items),
            "items": items,
            "cache_hit": call_number == 2,
        }

    _patch_run_dependencies(
        monkeypatch,
        expected_seed_source=args.seed_source,
        upsert_count=3,
        observed_seed_row_count=3,
        payload_builder=payload_builder,
    )

    report = await _run_script(args)

    assert report["status"] == "success"
    assert report["upsert_count"] == 3
    assert report["seed_row_count"] == 3
    seed_validation = _require_dict(report["seed_validation"])
    assert seed_validation["observed"] == 3
    assert seed_validation["expected"] == 3
    assert seed_validation["ok"] is True
    mcp = _require_dict(report["mcp"])
    assert mcp["expected_count"] == 3


@pytest.mark.anyio
async def test_run_success_limit_one(monkeypatch: pytest.MonkeyPatch) -> None:
    args = _make_args(1)

    def payload_builder(
        call_number: int, query: dict[str, object]
    ) -> dict[str, object]:
        limit, dong = _extract_limit_and_dong(query)
        items = _build_items(source=args.seed_source, dong=dong, limit=limit)
        return {
            "count": len(items),
            "items": items,
            "cache_hit": call_number == 2,
        }

    _patch_run_dependencies(
        monkeypatch,
        expected_seed_source=args.seed_source,
        upsert_count=3,
        observed_seed_row_count=3,
        payload_builder=payload_builder,
    )

    report = await _run_script(args)

    assert report["status"] == "success"
    mcp = _require_dict(report["mcp"])
    assert mcp["expected_count"] == 1
    first_call = _require_dict(mcp["first_call"])
    second_call = _require_dict(mcp["second_call"])
    assert first_call["count"] == 1
    assert second_call["count"] == 1


@pytest.mark.anyio
async def test_run_fails_on_partial_upsert(monkeypatch: pytest.MonkeyPatch) -> None:
    args = _make_args(3)

    def payload_builder(
        call_number: int, query: dict[str, object]
    ) -> dict[str, object]:
        limit, dong = _extract_limit_and_dong(query)
        items = _build_items(source=args.seed_source, dong=dong, limit=limit)
        return {
            "count": len(items),
            "items": items,
            "cache_hit": call_number == 2,
        }

    _patch_run_dependencies(
        monkeypatch,
        expected_seed_source=args.seed_source,
        upsert_count=2,
        observed_seed_row_count=3,
        payload_builder=payload_builder,
    )

    report = await _run_script(args)

    assert report["status"] == "failure"
    failures = report.get("failures")
    assert isinstance(failures, list)
    assert "upsert_count != seed_row_count" in failures


@pytest.mark.anyio
async def test_run_fails_on_seed_validation_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = _make_args(3)

    def payload_builder(
        call_number: int, query: dict[str, object]
    ) -> dict[str, object]:
        limit, dong = _extract_limit_and_dong(query)
        items = _build_items(source=args.seed_source, dong=dong, limit=limit)
        return {
            "count": len(items),
            "items": items,
            "cache_hit": call_number == 2,
        }

    _patch_run_dependencies(
        monkeypatch,
        expected_seed_source=args.seed_source,
        upsert_count=3,
        observed_seed_row_count=2,
        payload_builder=payload_builder,
    )

    report = await _run_script(args)

    assert report["status"] == "failure"
    failures = report.get("failures")
    assert isinstance(failures, list)
    assert "seed_validation_count_mismatch" in failures
    seed_validation = _require_dict(report["seed_validation"])
    assert seed_validation["observed"] == 2
    assert seed_validation["expected"] == 3
    assert seed_validation["ok"] is False


@pytest.mark.anyio
async def test_run_expected_count_tracks_seed_row_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = _make_args(3)
    original_build_seed_rows = naver_check._build_seed_rows

    def fake_build_seed_rows(
        seed_source: str, seed_dong: str, run_id: str
    ) -> list[object]:
        return cast(
            list[object],
            original_build_seed_rows(seed_source, seed_dong, run_id)[:2],
        )

    def payload_builder(
        call_number: int, query: dict[str, object]
    ) -> dict[str, object]:
        limit, dong = _extract_limit_and_dong(query)
        items = _build_items(source=args.seed_source, dong=dong, limit=limit)[:2]
        return {
            "count": len(items),
            "items": items,
            "cache_hit": call_number == 2,
        }

    monkeypatch.setattr(
        "scripts.e2e_naver_mcp_check._build_seed_rows",
        fake_build_seed_rows,
    )
    _patch_run_dependencies(
        monkeypatch,
        expected_seed_source=args.seed_source,
        upsert_count=2,
        observed_seed_row_count=2,
        expected_seed_rows_len=2,
        payload_builder=payload_builder,
    )

    report = await _run_script(args)

    assert report["status"] == "success"
    assert report["seed_row_count"] == 2
    mcp = _require_dict(report["mcp"])
    assert mcp["expected_count"] == 2
    first_call = _require_dict(mcp["first_call"])
    second_call = _require_dict(mcp["second_call"])
    assert first_call["count"] == 2
    assert second_call["count"] == 2


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("mismatch_call_number", "expected_failure"),
    [
        (1, "first_call_source_mismatch"),
        (2, "second_call_source_mismatch"),
    ],
)
async def test_run_fails_on_source_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    mismatch_call_number: int,
    expected_failure: str,
) -> None:
    args = _make_args(3)

    def payload_builder(
        call_number: int, query: dict[str, object]
    ) -> dict[str, object]:
        limit, dong = _extract_limit_and_dong(query)
        source = (
            "wrong_source" if call_number == mismatch_call_number else args.seed_source
        )
        items = _build_items(source=source, dong=dong, limit=limit)
        return {
            "count": len(items),
            "items": items,
            "cache_hit": call_number == 2,
        }

    _patch_run_dependencies(
        monkeypatch,
        expected_seed_source=args.seed_source,
        upsert_count=3,
        observed_seed_row_count=3,
        payload_builder=payload_builder,
    )

    report = await _run_script(args)

    assert report["status"] == "failure"
    failures = report.get("failures")
    assert isinstance(failures, list)
    assert expected_failure in failures


@pytest.mark.anyio
async def test_run_fails_when_mcp_limit_not_positive() -> None:
    run_impl = cast(
        Callable[[naver_check.CliArgs], Awaitable[dict[str, object]]],
        getattr(naver_check, "_run"),
    )
    with pytest.raises(RuntimeError, match="--mcp-limit must be greater than 0"):
        _ = await run_impl(_make_args(0))
