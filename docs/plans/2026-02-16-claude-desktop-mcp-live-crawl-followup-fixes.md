# Claude Desktop MCP Live-Crawl Follow-up Fixes Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Close the gap between the approved live-crawl design and current implementation by adding retry coverage for retryable 5xx, jittered backoff, and configurable base pacing in Zigbang crawling.

**Architecture:** Keep the current `ZigbangCrawler` and one-shot manual prep script structure, but harden the HTTP request loop with a single retry policy function that handles 429 + retryable 5xx and jitter. Route base pacing through crawler config so script flags control both normal cadence and retry delays.

**Tech Stack:** Python 3.12, httpx, asyncio, pytest, ruff, uv.

---

### Task 1: Add Failing Tests for Retryable 5xx + Jittered Backoff Contract

**Files:**
- Modify: `/Users/robin/PycharmProjects/rent_radar/tests/test_zigbang_crawler.py`

**Step 1: Add failing test for retry on HTTP 500 then success**

```python
async def test_search_retries_on_500_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    ...
    assert attempts == 2
    assert rows
```

**Step 2: Add failing test for non-retryable 4xx (for example 404) immediate stop**

```python
async def test_search_does_not_retry_on_404(monkeypatch: pytest.MonkeyPatch) -> None:
    ...
    assert attempts == 1
    assert rows == []
```

**Step 3: Add failing test that jitter is applied via RNG hook**

```python
async def test_retry_backoff_applies_jitter(monkeypatch: pytest.MonkeyPatch) -> None:
    ...
    assert observed_sleep_seconds == [expected_with_jitter]
```

**Step 4: Run targeted tests and confirm failure first**

Run: `uv run pytest /Users/robin/PycharmProjects/rent_radar/tests/test_zigbang_crawler.py -q`
Expected: FAIL on new retry policy expectations.

**Step 5: Commit tests**

```bash
git add /Users/robin/PycharmProjects/rent_radar/tests/test_zigbang_crawler.py
git commit -m "test: define retryable 5xx and jitter backoff behavior"
```

### Task 2: Implement Retry Policy for 429 + Retryable 5xx with Jitter

**Files:**
- Modify: `/Users/robin/PycharmProjects/rent_radar/src/crawlers/zigbang.py`
- Modify: `/Users/robin/PycharmProjects/rent_radar/tests/test_zigbang_crawler.py`

**Step 1: Define retryable status set and jitter ratio constants**

```python
RETRYABLE_HTTP_STATUS_CODES: Final = {429, 500, 502, 503, 504}
DEFAULT_JITTER_RATIO: Final = 0.2
```

**Step 2: Add jitter helper**

```python
def _apply_jitter(self, base_seconds: float) -> float:
    ...
```

**Step 3: Update `_request_json_with_retry`**

```python
if status_code not in RETRYABLE_HTTP_STATUS_CODES:
    return None
...
sleep_seconds = self._apply_jitter(backoff_seconds)
await asyncio.sleep(sleep_seconds)
```

**Step 4: Keep cooldown trigger tied to repeated 429 only**

```python
if status_code == 429:
    consecutive_429 += 1
else:
    consecutive_429 = 0
```

**Step 5: Re-run crawler tests**

Run: `uv run pytest /Users/robin/PycharmProjects/rent_radar/tests/test_zigbang_crawler.py -q`
Expected: PASS.

**Step 6: Commit implementation**

```bash
git add /Users/robin/PycharmProjects/rent_radar/src/crawlers/zigbang.py /Users/robin/PycharmProjects/rent_radar/tests/test_zigbang_crawler.py
git commit -m "feat: add retryable 5xx and jittered backoff to zigbang crawler"
```

### Task 3: Wire Base Pacing to Configurable Crawler Option

**Files:**
- Modify: `/Users/robin/PycharmProjects/rent_radar/src/crawlers/zigbang.py`
- Modify: `/Users/robin/PycharmProjects/rent_radar/tests/test_zigbang_crawler.py`

**Step 1: Replace hardcoded request pacing**

```python
await asyncio.sleep(self._base_delay_seconds)
```

Replace in:
- loop pre-request sleep (`1.0`)
- optional chunk sleep (`2.0`) with derived pacing (for example `self._base_delay_seconds * 2`)

**Step 2: Add test asserting configured base delay is used**

```python
async def test_run_uses_configured_base_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    ...
    assert observed_sleeps[0] == 1.5
```

**Step 3: Run targeted tests**

Run: `uv run pytest /Users/robin/PycharmProjects/rent_radar/tests/test_zigbang_crawler.py -q`
Expected: PASS.

**Step 4: Commit**

```bash
git add /Users/robin/PycharmProjects/rent_radar/src/crawlers/zigbang.py /Users/robin/PycharmProjects/rent_radar/tests/test_zigbang_crawler.py
git commit -m "refactor: make zigbang crawl pacing configurable via base delay"
```

### Task 4: Strengthen Manual Prep Script Validation and Reporting

**Files:**
- Modify: `/Users/robin/PycharmProjects/rent_radar/scripts/manual_prepare_mcp_live_data.py`
- Modify: `/Users/robin/PycharmProjects/rent_radar/tests/test_manual_prepare_mcp_live_data.py`

**Step 1: Add explicit numeric input validation**

```python
if args.max_retries < 0:
    failures.append("max_retries < 0")
if args.base_delay_seconds < 0:
    failures.append("base_delay_seconds < 0")
if args.max_backoff_seconds < args.base_delay_seconds:
    failures.append("max_backoff_seconds < base_delay_seconds")
```

**Step 2: Add tests for invalid numeric args**

```python
@pytest.mark.anyio
async def test_run_reports_failure_on_invalid_backoff_range(...) -> None:
    ...
```

**Step 3: Decide policy for crawl errors and codify**

Option A (recommended): keep success if data persisted, but include `warnings`.
Option B: treat non-empty `crawl.errors` as failure.

Implement one policy and add test.

**Step 4: Run script tests**

Run: `uv run pytest /Users/robin/PycharmProjects/rent_radar/tests/test_manual_prepare_mcp_live_data.py -q`
Expected: PASS.

**Step 5: Commit**

```bash
git add /Users/robin/PycharmProjects/rent_radar/scripts/manual_prepare_mcp_live_data.py /Users/robin/PycharmProjects/rent_radar/tests/test_manual_prepare_mcp_live_data.py
git commit -m "refactor: validate manual prep script args and report policy explicitly"
```

### Task 5: Sync Playbook and README with Final Retry/Pacing Behavior

**Files:**
- Modify: `/Users/robin/PycharmProjects/rent_radar/docs/playbooks/claude-desktop-mcp-manual-test.md`
- Modify: `/Users/robin/PycharmProjects/rent_radar/README.md`

**Step 1: Document retryable status policy**

```markdown
Retry targets: 429, 500, 502, 503, 504
Backoff: exponential + jitter
Cooldown: applied on repeated 429
```

**Step 2: Clarify base pacing meaning**

```markdown
`--base-delay-seconds` affects both normal request cadence and retry backoff baseline.
```

**Step 3: Add narrow-query examples to reduce oversized responses**

```markdown
분당구 정자동 아파트 전세, 보증금 5억~8억, 10개만
```

**Step 4: Commit docs**

```bash
git add /Users/robin/PycharmProjects/rent_radar/docs/playbooks/claude-desktop-mcp-manual-test.md /Users/robin/PycharmProjects/rent_radar/README.md
git commit -m "docs: align manual mcp live-crawl docs with retry and pacing behavior"
```

### Task 6: Verification Gate

**Files:**
- Modify: all files touched in Tasks 1-5

**Step 1: Run focused tests**

Run: `uv run pytest /Users/robin/PycharmProjects/rent_radar/tests/test_zigbang_crawler.py /Users/robin/PycharmProjects/rent_radar/tests/test_manual_prepare_mcp_live_data.py -q`
Expected: PASS.

**Step 2: Run MCP regression tests**

Run: `uv run pytest /Users/robin/PycharmProjects/rent_radar/tests/test_mcp_search_rent.py /Users/robin/PycharmProjects/rent_radar/tests/test_mcp_region_tools.py /Users/robin/PycharmProjects/rent_radar/tests/test_mcp_favorite_tools.py -q`
Expected: PASS.

**Step 3: Run lint checks**

Run: `uv run ruff check /Users/robin/PycharmProjects/rent_radar/src/crawlers/zigbang.py /Users/robin/PycharmProjects/rent_radar/scripts/manual_prepare_mcp_live_data.py /Users/robin/PycharmProjects/rent_radar/tests/test_zigbang_crawler.py /Users/robin/PycharmProjects/rent_radar/tests/test_manual_prepare_mcp_live_data.py`
Expected: PASS.

**Step 4: Final commit**

```bash
git add -A
git commit -m "fix: close retry and pacing gaps in claude desktop mcp live-crawl flow"
```
