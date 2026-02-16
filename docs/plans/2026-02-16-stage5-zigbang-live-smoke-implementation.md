# Stage 5 Zigbang Live Smoke Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a dedicated local live-smoke command for `crawl_zigbang_listings` with `ok|schema_mismatch` success contract, while preserving fail-fast safety and documenting Stage 5 operations evidence.

**Architecture:** Create a standalone smoke script that calls the existing crawl task path (`crawl_zigbang_listings.original_func`) and normalizes outcomes into a stable JSON report + exit code. Keep fail-fast semantics in core crawler/task logic, and enforce Stage 5 behavior at the smoke boundary only. Update runbook/checklist to make results reproducible and auditable.

**Tech Stack:** Python 3.12, TaskIQ decorated task (`original_func`), pytest, ruff, Markdown docs.

---

Implementation notes:
- Follow `@test-driven-development` for script contract behavior.
- Use `@verification-before-completion` before marking Stage 5 items complete.

### Task 1: Add failing tests for live-smoke contract classification

**Files:**
- Create: `/Users/robin/.codex/worktrees/478e/rent_radar/tests/test_smoke_zigbang_live_crawl.py`

**Step 1: Write failing tests for status classification and exit code**

```python
from __future__ import annotations

import importlib
from typing import Any, cast

import pytest

from src.crawlers.zigbang import ZigbangSchemaMismatchError

smoke = importlib.import_module("scripts.smoke_zigbang_live_crawl")

pytestmark = pytest.mark.anyio


async def test_run_reports_success_when_task_status_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_original_func() -> dict[str, object]:
        return {
            "source": "zigbang",
            "status": "ok",
            "fetched": 3,
            "count": 2,
            "deactivated": 1,
        }

    monkeypatch.setattr(smoke.crawl_zigbang_listings, "original_func", fake_original_func)
    report = await smoke._run(smoke.CliArgs(fingerprint="manual-smoke", allow_duplicate_run=False))
    assert report["status"] == "ok"
    assert report["result"] == "success"


async def test_run_reports_success_when_schema_mismatch_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_original_func() -> dict[str, object]:
        raise ZigbangSchemaMismatchError("raw_count=10 parsed_count=0")

    monkeypatch.setattr(smoke.crawl_zigbang_listings, "original_func", fake_original_func)
    report = await smoke._run(smoke.CliArgs(fingerprint="manual-smoke", allow_duplicate_run=False))
    assert report["status"] == "schema_mismatch"
    assert report["result"] == "success"


async def test_run_reports_failure_when_skipped_duplicate_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_original_func() -> dict[str, object]:
        return {"source": "zigbang", "status": "skipped_duplicate_execution", "count": 0}

    monkeypatch.setattr(smoke.crawl_zigbang_listings, "original_func", fake_original_func)
    report = await smoke._run(smoke.CliArgs(fingerprint="manual-smoke", allow_duplicate_run=False))
    assert report["status"] == "skipped_duplicate_execution"
    assert report["result"] == "failure"
```

**Step 2: Run targeted tests and confirm failure first**

Run: `uv run pytest /Users/robin/.codex/worktrees/478e/rent_radar/tests/test_smoke_zigbang_live_crawl.py -q`
Expected: FAIL (script/functions not yet implemented).

**Step 3: Commit failing tests**

```bash
git add /Users/robin/.codex/worktrees/478e/rent_radar/tests/test_smoke_zigbang_live_crawl.py
git commit -m "test: define stage5 zigbang live smoke status contract"
```

### Task 2: Implement Stage 5 smoke script (JSON report + exit code)

**Files:**
- Create: `/Users/robin/.codex/worktrees/478e/rent_radar/scripts/smoke_zigbang_live_crawl.py`
- Modify: `/Users/robin/.codex/worktrees/478e/rent_radar/tests/test_smoke_zigbang_live_crawl.py`

**Step 1: Implement CLI args and core runner**

```python
@dataclass(frozen=True)
class CliArgs:
    fingerprint: str = "manual-smoke"
    allow_duplicate_run: bool = False


async def _run(args: CliArgs) -> dict[str, object]:
    ...
```

**Step 2: Call task path and normalize outcomes**

```python
raw_result = await crawl_zigbang_listings.original_func()
status = str(raw_result.get("status", "unknown"))
if status == "ok":
    result = "success"
elif status == "skipped_duplicate_execution" and not args.allow_duplicate_run:
    result = "failure"
...
except ZigbangSchemaMismatchError as exc:
    status = "schema_mismatch"
    result = "success"
    reason = str(exc)
```

**Step 3: Add JSON-only main and exit code contract**

```python
print(json.dumps(report, ensure_ascii=False, indent=2))
return 0 if report.get("result") == "success" else 1
```

**Step 4: Expand tests for `action_hint` and unknown exception path**

```python
assert "action_hint" in report
assert report["result"] == "failure"
```

**Step 5: Run tests**

Run: `uv run pytest /Users/robin/.codex/worktrees/478e/rent_radar/tests/test_smoke_zigbang_live_crawl.py -q`
Expected: PASS.

**Step 6: Commit implementation**

```bash
git add /Users/robin/.codex/worktrees/478e/rent_radar/scripts/smoke_zigbang_live_crawl.py /Users/robin/.codex/worktrees/478e/rent_radar/tests/test_smoke_zigbang_live_crawl.py
git commit -m "feat: add stage5 zigbang live smoke command"
```

### Task 3: Re-verify fail-fast before upsert via task-path regression test

**Files:**
- Modify: `/Users/robin/.codex/worktrees/478e/rent_radar/tests/test_tasks.py`

**Step 1: Add failing test proving `_persist_listings` is not called on schema mismatch**

```python
@pytest.mark.anyio
async def test_crawl_zigbang_schema_mismatch_fails_before_upsert(monkeypatch: pytest.MonkeyPatch) -> None:
    called = {"persist": 0}

    async def fake_run(self: object) -> CrawlResult[ListingUpsert]:
        raise ZigbangSchemaMismatchError("raw_count=5 parsed_count=0")

    async def fake_persist(_rows: list[ListingUpsert]) -> int:
        called["persist"] += 1
        return 0

    ...
    assert result.is_err
    assert called["persist"] == 0
```

**Step 2: Run targeted test**

Run: `uv run pytest /Users/robin/.codex/worktrees/478e/rent_radar/tests/test_tasks.py::test_crawl_zigbang_schema_mismatch_fails_before_upsert -q`
Expected: PASS (or FAIL if behavior drifted).

**Step 3: Commit**

```bash
git add /Users/robin/.codex/worktrees/478e/rent_radar/tests/test_tasks.py
git commit -m "test: verify zigbang schema mismatch fails before upsert"
```

### Task 4: Update Stage 5 runbook and checklist

**Files:**
- Modify: `/Users/robin/.codex/worktrees/478e/rent_radar/docs/playbooks/claude-desktop-mcp-manual-test.md`
- Modify: `/Users/robin/.codex/worktrees/478e/rent_radar/ROADMAP_MCP_CHECKLIST.md`

**Step 1: Add Stage 5 live smoke run section to playbook**

```markdown
## Stage 5 Live Smoke (Local Manual)

uv run python scripts/smoke_zigbang_live_crawl.py --fingerprint stage5-smoke-20260216
```

Include:
- Success contract: `status in {ok, schema_mismatch}`
- Failure interpretation for `skipped_duplicate_execution`, network failures, unexpected exception
- Action hints for each failure mode

**Step 2: Update checklist Stage 5 items and evidence template**

```markdown
- [ ] Add `crawl_zigbang_listings` live smoke (`ok` or `schema_mismatch` contract)
...
| 2026-02-16 | Stage 5 live smoke | `uv run python scripts/smoke_zigbang_live_crawl.py ...` -> `status=...` |
```

**Step 3: Commit docs**

```bash
git add /Users/robin/.codex/worktrees/478e/rent_radar/docs/playbooks/claude-desktop-mcp-manual-test.md /Users/robin/.codex/worktrees/478e/rent_radar/ROADMAP_MCP_CHECKLIST.md
git commit -m "docs: add stage5 zigbang live smoke runbook and checklist flow"
```

### Task 5: Verification gate and final Stage 5 evidence refresh

**Files:**
- Modify: all files touched in Tasks 1-4

**Step 1: Run focused tests**

Run: `uv run pytest /Users/robin/.codex/worktrees/478e/rent_radar/tests/test_smoke_zigbang_live_crawl.py /Users/robin/.codex/worktrees/478e/rent_radar/tests/test_tasks.py /Users/robin/.codex/worktrees/478e/rent_radar/tests/test_zigbang_crawler.py -q`
Expected: PASS.

**Step 2: Run live smoke command for dated evidence**

Run: `uv run python /Users/robin/.codex/worktrees/478e/rent_radar/scripts/smoke_zigbang_live_crawl.py --fingerprint stage5-smoke-20260216`
Expected: JSON output with `result=success` and `status` either `ok` or `schema_mismatch`.

**Step 3: Run lint**

Run: `uv run ruff check /Users/robin/.codex/worktrees/478e/rent_radar/scripts/smoke_zigbang_live_crawl.py /Users/robin/.codex/worktrees/478e/rent_radar/tests/test_smoke_zigbang_live_crawl.py /Users/robin/.codex/worktrees/478e/rent_radar/tests/test_tasks.py`
Expected: PASS.

**Step 4: Final docs/evidence commit**

```bash
git add -A
git commit -m "chore: complete stage5 zigbang live smoke verification evidence"
```
