# Stage 6 Naver 429 Observer (Phase 1) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a local, observer-only Naver live probe runner that fails immediately on first HTTP 429 and emits deterministic JSON evidence.

**Architecture:** Implement a standalone script (`scripts/observe_naver_429.py`) that performs narrow `articles` requests against Naver, captures the first rate-limit context, and exits with contract-based status codes. Keep this phase non-invasive: no TaskIQ wiring, no DB writes, no MCP response shape changes.

**Tech Stack:** Python 3.12, httpx, asyncio, argparse, pytest, ruff, Markdown docs.

---

Implementation notes:
- Follow `@test-driven-development` for all behavior changes.
- Use `@verification-before-completion` before claiming Stage 6 phase-1 complete.

### Task 1: Add failing tests for 429 fail-fast observer contract

**Files:**
- Create: `/Users/robin/.codex/worktrees/3aa5/rent_radar/tests/test_observe_naver_429.py`

**Step 1: Write failing tests for status classification and immediate stop**

```python
from __future__ import annotations

import importlib
from typing import Any

import pytest

observer = importlib.import_module("scripts.observe_naver_429")
pytestmark = pytest.mark.anyio


class DummyResponse:
    def __init__(self, status_code: int, headers: dict[str, str] | None = None) -> None:
        self.status_code = status_code
        self.headers = headers or {}


async def test_run_fails_immediately_on_first_429(monkeypatch: pytest.MonkeyPatch) -> None:
    seen_calls: list[dict[str, str]] = []

    async def fake_request(**kwargs: Any) -> DummyResponse:
        seen_calls.append({"region_code": kwargs["region_code"], "property_type": kwargs["property_type"]})
        return DummyResponse(429, headers={"Retry-After": "7", "X-RateLimit-Remaining": "0"})

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


async def test_run_succeeds_when_no_429(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_request(**kwargs: Any) -> DummyResponse:
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


async def test_run_reports_error_on_unexpected_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_request(**kwargs: Any) -> DummyResponse:
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
```

**Step 2: Run targeted tests and confirm failure first**

Run: `uv run pytest /Users/robin/.codex/worktrees/3aa5/rent_radar/tests/test_observe_naver_429.py -q`  
Expected: FAIL (module or symbols not implemented yet).

**Step 3: Commit failing tests**

```bash
git add /Users/robin/.codex/worktrees/3aa5/rent_radar/tests/test_observe_naver_429.py
git commit -m "test: define stage6 naver 429 observer fail-fast contract"
```

### Task 2: Implement observer script core loop and JSON contract

**Files:**
- Create: `/Users/robin/.codex/worktrees/3aa5/rent_radar/scripts/observe_naver_429.py`
- Modify: `/Users/robin/.codex/worktrees/3aa5/rent_radar/tests/test_observe_naver_429.py`

**Step 1: Implement CLI dataclass and argument parser**

```python
@dataclass(frozen=True)
class CliArgs:
    region_codes: list[str]
    property_types: list[str]
    max_regions: int
    requests_per_region: int
    timeout_seconds: float
    fingerprint: str
```

**Step 2: Implement Naver request function using legacy endpoint shape**

```python
BASE_URL: Final = "https://new.land.naver.com/api"
TRADE_TYPES: Final = ("B1", "B2")

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
```

**Step 3: Implement fail-fast runner with injectable `request_fn` for tests**

```python
RequestFn = Callable[..., Awaitable[object]]

async def _run(args: CliArgs, request_fn: RequestFn | None = None) -> dict[str, object]:
    # iterate region/property/trade/request-index; fail immediately on first 429
    ...
```

Rules:
- First `429` => `status=rate_limited`, `result=failure`, immediate return.
- No `429` => `status=ok`, `result=success`.
- Exception => `status=error`, `result=failure`.

**Step 4: Implement JSON main and exit code mapping**

```python
print(json.dumps(report, ensure_ascii=False, indent=2))
return 0 if report["status"] == "ok" else 1 if report["status"] == "rate_limited" else 2
```

**Step 5: Re-run tests**

Run: `uv run pytest /Users/robin/.codex/worktrees/3aa5/rent_radar/tests/test_observe_naver_429.py -q`  
Expected: PASS.

**Step 6: Commit implementation**

```bash
git add /Users/robin/.codex/worktrees/3aa5/rent_radar/scripts/observe_naver_429.py /Users/robin/.codex/worktrees/3aa5/rent_radar/tests/test_observe_naver_429.py
git commit -m "feat: add stage6 naver 429 observer runner"
```

### Task 3: Add strict report fields and header capture tests

**Files:**
- Modify: `/Users/robin/.codex/worktrees/3aa5/rent_radar/tests/test_observe_naver_429.py`
- Modify: `/Users/robin/.codex/worktrees/3aa5/rent_radar/scripts/observe_naver_429.py`

**Step 1: Add failing tests for output schema and context completeness**

```python
async def test_rate_limited_report_contains_context_and_headers(...) -> None:
    ...
    assert report["first_429"]["region_code"] == "11680"
    assert report["first_429"]["request_index"] == 1
    assert "response_headers_subset" in report["first_429"]
    assert "action_hint" in report

async def test_invalid_cli_values_raise_parser_error(...) -> None:
    ...
```

**Step 2: Run targeted tests to confirm initial failure**

Run: `uv run pytest /Users/robin/.codex/worktrees/3aa5/rent_radar/tests/test_observe_naver_429.py -q`  
Expected: FAIL on newly added assertions.

**Step 3: Implement report schema hardening**

```python
def _extract_rate_limit_headers(headers: Mapping[str, str]) -> dict[str, str]:
    keys = ("retry-after", "x-ratelimit-remaining", "x-ratelimit-reset")
    ...
```

Ensure report always includes:
- `executed_at`, `fingerprint`
- `summary` with `attempted_requests`, `regions_attempted`, `first_429_at_request_index`
- `first_429` (nullable)
- `action_hint`

**Step 4: Re-run tests**

Run: `uv run pytest /Users/robin/.codex/worktrees/3aa5/rent_radar/tests/test_observe_naver_429.py -q`  
Expected: PASS.

**Step 5: Commit schema hardening**

```bash
git add /Users/robin/.codex/worktrees/3aa5/rent_radar/scripts/observe_naver_429.py /Users/robin/.codex/worktrees/3aa5/rent_radar/tests/test_observe_naver_429.py
git commit -m "test: harden stage6 observer report schema and header capture"
```

### Task 4: Update playbook and roadmap for Stage 6 phase-1 operation

**Files:**
- Modify: `/Users/robin/.codex/worktrees/3aa5/rent_radar/docs/playbooks/claude-desktop-mcp-manual-test.md`
- Modify: `/Users/robin/.codex/worktrees/3aa5/rent_radar/ROADMAP_MCP_CHECKLIST.md`

**Step 1: Add Stage 6 observer section to playbook**

```markdown
## Stage 6 Naver 429 Observer (Local Manual)

uv run python scripts/observe_naver_429.py --region-codes 11680 --property-types APT --max-regions 1 --requests-per-region 5 --fingerprint stage6-observe-20260217
```

Document:
- contract (`ok` vs `rate_limited` vs `error`)
- first-429 immediate stop rule
- how to log evidence fields into roadmap.

**Step 2: Update Stage 6 checklist items for phase-1 evidence**

Example:
```markdown
- [x] Add Naver 429 observer runner with first-429 fail-fast contract
  - Evidence: `uv run python scripts/observe_naver_429.py ...` -> `status=rate_limited`, `first_429.request_index=1`
```

**Step 3: Commit docs**

```bash
git add /Users/robin/.codex/worktrees/3aa5/rent_radar/docs/playbooks/claude-desktop-mcp-manual-test.md /Users/robin/.codex/worktrees/3aa5/rent_radar/ROADMAP_MCP_CHECKLIST.md
git commit -m "docs: add stage6 naver 429 observer runbook and checklist evidence"
```

### Task 5: Verification gate and evidence refresh

**Files:**
- Modify: all files touched in Tasks 1-4

**Step 1: Run focused tests**

Run: `uv run pytest /Users/robin/.codex/worktrees/3aa5/rent_radar/tests/test_observe_naver_429.py -q`  
Expected: PASS.

**Step 2: Run lint checks**

Run: `uv run ruff check /Users/robin/.codex/worktrees/3aa5/rent_radar/scripts/observe_naver_429.py /Users/robin/.codex/worktrees/3aa5/rent_radar/tests/test_observe_naver_429.py`  
Expected: PASS.

**Step 3: Run local manual live observer for dated evidence**

Run:
`uv run python /Users/robin/.codex/worktrees/3aa5/rent_radar/scripts/observe_naver_429.py --region-codes 11680 --property-types APT --max-regions 1 --requests-per-region 5 --fingerprint stage6-observe-20260217`

Expected:
- Either `status=rate_limited` (likely in current phase) or `status=ok`
- Deterministic JSON output with `summary` and `first_429` contract fields.

**Step 4: Final evidence commit**

```bash
git add -A
git commit -m "chore: complete stage6 naver 429 observer verification evidence"
```
