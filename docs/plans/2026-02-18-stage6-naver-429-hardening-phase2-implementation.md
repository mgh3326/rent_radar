# Stage 6 Naver 429 Hardening (Phase 2) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Restore Naver TaskIQ crawl path with Retry-After-first 429 handling, throttling, hard-failure semantics, and Stage 6 live-smoke acceptance (`inserted > 0`).

**Architecture:** Reintroduce a dedicated `NaverCrawler` for live listing fetches and integrate it into TaskIQ via `crawl_naver_listings` + enqueue dedup helper. Keep policy explicit: 429 retries are bounded and must resolve to success or hard `error` (no degraded status). Add a dedicated smoke script and docs/checklist updates to make Stage 6 Phase 2 auditable.

**Tech Stack:** Python 3.12, httpx, asyncio, TaskIQ, pytest(anyio), ruff, existing repository/session abstractions

---

I'm using the writing-plans skill to create the implementation plan.

## Implementation Guardrails

- Use `@test-driven-development`: test first, then minimum code.
- Use `@verification-before-completion` before any "done" claim.
- Keep MCP response schema unchanged.
- Keep status contract simple: `ok | skipped_duplicate_execution | error`.
- YAGNI: do not restore web-trigger paths in this phase.

### Task 1: Restore Naver crawler baseline module and parser contract

**Files:**
- Create: `/Users/robin/.codex/worktrees/5539/rent_radar/src/crawlers/naver.py`
- Modify: `/Users/robin/.codex/worktrees/5539/rent_radar/tests/test_naver_crawler.py`

**Step 1: Write failing parser contract tests**

```python
@pytest.mark.anyio
async def test_naver_crawler_parse_article(naver_article_json: list[dict]) -> None:
    crawler = NaverCrawler(region_codes=["11110"], property_types=["APT"])
    row = crawler._parse_article(naver_article_json[0], "11110")
    assert row is not None
    assert row.source == "naver"
    assert row.source_id == "123456"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest /Users/robin/.codex/worktrees/5539/rent_radar/tests/test_naver_crawler.py::test_naver_crawler_parse_article -q`  
Expected: FAIL with import/module error for `src.crawlers.naver`.

**Step 3: Write minimal crawler and parse implementation**

```python
class NaverCrawler:
    def __init__(self, region_codes: list[str] | None = None, property_types: list[str] | None = None) -> None:
        self._region_codes = region_codes or settings.target_region_codes
        self._property_types = property_types or ["APT", "VILLA", "OPST", "ONEROOM"]

    def _parse_article(self, article: dict[str, object], region_code: str) -> ListingUpsert | None:
        article_no = str(article.get("articleNo", "")).strip()
        if not article_no:
            return None
        return ListingUpsert(...)
```

**Step 4: Run crawler parser test file**

Run: `uv run pytest /Users/robin/.codex/worktrees/5539/rent_radar/tests/test_naver_crawler.py -q`  
Expected: PASS.

**Step 5: Commit**

```bash
git add /Users/robin/.codex/worktrees/5539/rent_radar/src/crawlers/naver.py /Users/robin/.codex/worktrees/5539/rent_radar/tests/test_naver_crawler.py
git commit -m "feat: restore naver crawler parser baseline"
```

### Task 2: Implement 429 retry policy (Retry-After first, fallback backoff+jitter)

**Files:**
- Modify: `/Users/robin/.codex/worktrees/5539/rent_radar/src/crawlers/naver.py`
- Modify: `/Users/robin/.codex/worktrees/5539/rent_radar/tests/test_naver_crawler.py`

**Step 1: Add failing tests for retry policy**

```python
@pytest.mark.anyio
async def test_request_articles_uses_retry_after_header_first(...) -> None:
    # first response 429 with Retry-After=7, next response 200
    # assert asyncio.sleep called with ~7 seconds (no exponential fallback)

@pytest.mark.anyio
async def test_request_articles_falls_back_to_exponential_backoff(...) -> None:
    # 429 without Retry-After; assert delays 1,2,4... with jitter hook
```

**Step 2: Run targeted tests (expect fail)**

Run: `uv run pytest /Users/robin/.codex/worktrees/5539/rent_radar/tests/test_naver_crawler.py -k "retry_after or exponential" -q`  
Expected: FAIL due to missing policy behavior.

**Step 3: Implement minimal retry policy in crawler request path**

```python
def _effective_retry_delay(self, response: httpx.Response, attempt: int) -> float:
    retry_after = response.headers.get("Retry-After")
    if retry_after is not None:
        parsed = _parse_retry_after_seconds(retry_after)
        if parsed is not None:
            return parsed
    base = min(self._base_delay_seconds * (2**attempt), self._max_backoff_seconds)
    return self._apply_jitter(base)
```

```python
if status_code == 429:
    if attempt >= self._max_retries:
        raise
    await asyncio.sleep(self._effective_retry_delay(response, attempt))
    continue
```

**Step 4: Re-run retry-focused tests**

Run: `uv run pytest /Users/robin/.codex/worktrees/5539/rent_radar/tests/test_naver_crawler.py -k "retry_after or exponential" -q`  
Expected: PASS.

**Step 5: Commit**

```bash
git add /Users/robin/.codex/worktrees/5539/rent_radar/src/crawlers/naver.py /Users/robin/.codex/worktrees/5539/rent_radar/tests/test_naver_crawler.py
git commit -m "feat: add retry-after first naver 429 retry policy"
```

### Task 3: Add throttling and hard-failure error reporting in crawler run

**Files:**
- Modify: `/Users/robin/.codex/worktrees/5539/rent_radar/src/crawlers/naver.py`
- Modify: `/Users/robin/.codex/worktrees/5539/rent_radar/tests/test_naver_crawler.py`

**Step 1: Add failing tests for throttle and hard failure**

```python
@pytest.mark.anyio
async def test_run_applies_base_throttle_before_each_request(...) -> None:
    # assert sleep invoked for request cadence

@pytest.mark.anyio
async def test_run_returns_error_context_when_429_retry_exhausted(...) -> None:
    # assert CrawlResult.errors contains 429 exhausted context
```

**Step 2: Run new tests (expect fail)**

Run: `uv run pytest /Users/robin/.codex/worktrees/5539/rent_radar/tests/test_naver_crawler.py -k "throttle or exhausted" -q`  
Expected: FAIL.

**Step 3: Implement minimum throttle + hard-failure context path**

```python
await asyncio.sleep(self._base_delay_seconds)
articles = await self._request_articles(...)
```

```python
except httpx.HTTPStatusError as exc:
    errors.append(
        f"HTTP {exc.response.status_code} exhausted retries for region_code={region_code}, property_type={property_type}, trade_type={trade_type}"
    )
    return CrawlResult(count=len(all_rows), rows=all_rows, errors=errors)
```

**Step 4: Re-run crawler test file**

Run: `uv run pytest /Users/robin/.codex/worktrees/5539/rent_radar/tests/test_naver_crawler.py -q`  
Expected: PASS.

**Step 5: Commit**

```bash
git add /Users/robin/.codex/worktrees/5539/rent_radar/src/crawlers/naver.py /Users/robin/.codex/worktrees/5539/rent_radar/tests/test_naver_crawler.py
git commit -m "feat: add naver throttle and retry-exhausted failure context"
```

### Task 4: Restore Naver TaskIQ task and enqueue helper

**Files:**
- Modify: `/Users/robin/.codex/worktrees/5539/rent_radar/src/taskiq_app/tasks.py`
- Modify: `/Users/robin/.codex/worktrees/5539/rent_radar/tests/test_tasks.py`

**Step 1: Write failing task tests**

```python
@pytest.mark.anyio
async def test_naver_task_paths_exposed() -> None:
    assert hasattr(task_module, "crawl_naver_listings")
    assert hasattr(task_module, "enqueue_crawl_naver_listings")

@pytest.mark.anyio
async def test_crawl_naver_listings_returns_error_on_exhausted_429(...) -> None:
    # mock crawler.run() -> CrawlResult(count=0, rows=[], errors=[...429...])
    # assert return_value["status"] == "error"
```

**Step 2: Run task tests (expect fail)**

Run: `uv run pytest /Users/robin/.codex/worktrees/5539/rent_radar/tests/test_tasks.py -k "naver" -q`  
Expected: FAIL because Naver task path is absent.

**Step 3: Add minimal task implementation with hard-failure contract**

```python
@broker.task(task_name="crawl_naver_listings", schedule=[{"cron": "0 */6 * * *"}], retry_on_error=True, max_retries=3)
async def crawl_naver_listings() -> dict[str, object]:
    ...
    result = await crawler.run()
    if result.errors:
        return {
            "source": "naver",
            "count": 0,
            "fetched": result.count,
            "status": "error",
            "reason": result.errors[0],
            "errors_count": len(result.errors),
        }
```

```python
async def enqueue_crawl_naver_listings(*, fingerprint: str = "manual") -> dict[str, object]:
    ...
```

**Step 4: Re-run task tests**

Run: `uv run pytest /Users/robin/.codex/worktrees/5539/rent_radar/tests/test_tasks.py -q`  
Expected: PASS including Naver-related scenarios.

**Step 5: Commit**

```bash
git add /Users/robin/.codex/worktrees/5539/rent_radar/src/taskiq_app/tasks.py /Users/robin/.codex/worktrees/5539/rent_radar/tests/test_tasks.py
git commit -m "feat: restore naver taskiq crawl path with hard failure contract"
```

### Task 5: Add Stage 6 Naver live smoke command and contract tests

**Files:**
- Create: `/Users/robin/.codex/worktrees/5539/rent_radar/scripts/smoke_naver_live_crawl.py`
- Create: `/Users/robin/.codex/worktrees/5539/rent_radar/tests/test_smoke_naver_live_crawl.py`

**Step 1: Write failing smoke contract tests**

```python
@pytest.mark.anyio
async def test_smoke_reports_success_only_when_inserted_positive(...) -> None:
    # mocked task result status=ok,count>0 => result=success

@pytest.mark.anyio
async def test_smoke_reports_failure_on_error_or_zero_inserted(...) -> None:
    # status=error or count=0 => result=failure
```

**Step 2: Run smoke tests (expect fail)**

Run: `uv run pytest /Users/robin/.codex/worktrees/5539/rent_radar/tests/test_smoke_naver_live_crawl.py -q`  
Expected: FAIL (missing script).

**Step 3: Implement smoke script with stable JSON contract**

```python
report = {
    "source": "naver",
    "fingerprint": args.fingerprint,
    "status": status,
    "result": "success" if status == "ok" and inserted > 0 else "failure",
    "task_result": raw_result,
}
```

**Step 4: Re-run smoke tests**

Run: `uv run pytest /Users/robin/.codex/worktrees/5539/rent_radar/tests/test_smoke_naver_live_crawl.py -q`  
Expected: PASS.

**Step 5: Commit**

```bash
git add /Users/robin/.codex/worktrees/5539/rent_radar/scripts/smoke_naver_live_crawl.py /Users/robin/.codex/worktrees/5539/rent_radar/tests/test_smoke_naver_live_crawl.py
git commit -m "feat: add stage6 naver live smoke command"
```

### Task 6: Update playbook + roadmap checklist (Phase 2 closure)

**Files:**
- Modify: `/Users/robin/.codex/worktrees/5539/rent_radar/docs/playbooks/claude-desktop-mcp-manual-test.md`
- Modify: `/Users/robin/.codex/worktrees/5539/rent_radar/ROADMAP_MCP_CHECKLIST.md`

**Step 1: Add failing doc assertions (lightweight guard test or grep checks)**

```bash
rg -n "Stage 6 Naver Live Smoke" /Users/robin/.codex/worktrees/5539/rent_radar/docs/playbooks/claude-desktop-mcp-manual-test.md
rg -n "Phase 2" /Users/robin/.codex/worktrees/5539/rent_radar/ROADMAP_MCP_CHECKLIST.md
```

Expected: missing/new strings before edit.

**Step 2: Update manual playbook section**

Add:
- `uv run python scripts/smoke_naver_live_crawl.py --fingerprint stage6-phase2-...`
- Success = `status=ok` and `count > 0`
- Failure interpretation for `error` and `count==0`

**Step 3: Update roadmap Phase 2 checkboxes and execution evidence template**

Add/mark:
- 429 policy implemented
- throttling strategy implemented
- hard-failure notification policy applied
- live acceptance verified (`inserted > 0`)
- Naver smoke + runbook updated

**Step 4: Run lint/static checks for touched files**

Run: `uv run ruff check /Users/robin/.codex/worktrees/5539/rent_radar/src/crawlers/naver.py /Users/robin/.codex/worktrees/5539/rent_radar/src/taskiq_app/tasks.py /Users/robin/.codex/worktrees/5539/rent_radar/scripts/smoke_naver_live_crawl.py /Users/robin/.codex/worktrees/5539/rent_radar/tests/test_naver_crawler.py /Users/robin/.codex/worktrees/5539/rent_radar/tests/test_tasks.py /Users/robin/.codex/worktrees/5539/rent_radar/tests/test_smoke_naver_live_crawl.py`  
Expected: `All checks passed!`

**Step 5: Commit**

```bash
git add /Users/robin/.codex/worktrees/5539/rent_radar/docs/playbooks/claude-desktop-mcp-manual-test.md /Users/robin/.codex/worktrees/5539/rent_radar/ROADMAP_MCP_CHECKLIST.md
git commit -m "docs: close stage6 phase2 naver hardening checklist and runbook"
```

### Task 7: Verification gate and final evidence refresh

**Files:**
- Modify: `/Users/robin/.codex/worktrees/5539/rent_radar/ROADMAP_MCP_CHECKLIST.md` (execution log row only, if needed)

**Step 1: Run full targeted test suite**

Run: `uv run pytest /Users/robin/.codex/worktrees/5539/rent_radar/tests/test_naver_crawler.py /Users/robin/.codex/worktrees/5539/rent_radar/tests/test_tasks.py /Users/robin/.codex/worktrees/5539/rent_radar/tests/test_smoke_naver_live_crawl.py -q`  
Expected: all pass.

**Step 2: Run live smoke for acceptance evidence**

Run: `uv run python /Users/robin/.codex/worktrees/5539/rent_radar/scripts/smoke_naver_live_crawl.py --fingerprint stage6-phase2-$(date +%Y%m%d)`  
Expected: JSON `result=success`, `status=ok`, `task_result.count > 0`.

**Step 3: Refresh execution log evidence line**

Update execution log with command + observed status/count.

**Step 4: Final verification command set**

Run:
- `uv run ruff check /Users/robin/.codex/worktrees/5539/rent_radar/src/crawlers/naver.py /Users/robin/.codex/worktrees/5539/rent_radar/src/taskiq_app/tasks.py /Users/robin/.codex/worktrees/5539/rent_radar/scripts/smoke_naver_live_crawl.py /Users/robin/.codex/worktrees/5539/rent_radar/tests/test_naver_crawler.py /Users/robin/.codex/worktrees/5539/rent_radar/tests/test_tasks.py /Users/robin/.codex/worktrees/5539/rent_radar/tests/test_smoke_naver_live_crawl.py`
- `uv run pytest /Users/robin/.codex/worktrees/5539/rent_radar/tests/test_naver_crawler.py /Users/robin/.codex/worktrees/5539/rent_radar/tests/test_tasks.py /Users/robin/.codex/worktrees/5539/rent_radar/tests/test_smoke_naver_live_crawl.py -q`

Expected: all pass.

**Step 5: Commit**

```bash
git add /Users/robin/.codex/worktrees/5539/rent_radar/ROADMAP_MCP_CHECKLIST.md
git commit -m "chore: record stage6 phase2 verification evidence"
```
