# Claude Desktop MCP Live-Crawl Manual Test Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a non-destructive live-crawl helper flow and Claude Desktop manual test playbook, with balanced 429 prevention in Zigbang crawling.

**Architecture:** Extend `ZigbangCrawler` with retry/backoff/cooldown controls and metrics, then add a one-shot script that runs crawl->upsert and emits a strict JSON report for manual MCP testing. Document the manual Claude Desktop flow in a playbook rather than building an automated MCP contract runner.

**Tech Stack:** Python 3.12, httpx, SQLAlchemy async, FastMCP, pytest, ruff, uv.

---

Execution notes:
- Apply `@superpowers/test-driven-development` for code tasks.
- Run `@superpowers/verification-before-completion` before final success claims.

### Task 1: Add Failing Tests for Zigbang Retry/429 Behavior

**Files:**
- Modify: `/Users/robin/PycharmProjects/rent_radar/tests/test_zigbang_crawler.py`

**Step 1: Write failing retry test for 429 then success**

```python
async def test_search_retries_on_429_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    crawler = ZigbangCrawler(region_names=["종로구"], property_types=["아파트"])
    ...
    assert attempts == 3
    assert rows
```

**Step 2: Write failing retry-exhaustion test**

```python
async def test_search_stops_after_max_retries_on_429(monkeypatch: pytest.MonkeyPatch) -> None:
    crawler = ZigbangCrawler(region_names=["종로구"], property_types=["아파트"])
    ...
    assert result == []
    assert crawler.last_run_metrics["retry_count"] > 0
```

**Step 3: Run targeted tests to confirm failure first**

Run: `uv run pytest /Users/robin/PycharmProjects/rent_radar/tests/test_zigbang_crawler.py -q`
Expected: FAIL due missing retry/backoff implementation.

**Step 4: Commit test-only change**

```bash
git add /Users/robin/PycharmProjects/rent_radar/tests/test_zigbang_crawler.py
git commit -m "test: define zigbang 429 retry behavior contract"
```

### Task 2: Implement Retry/Backoff/Cooldown in Zigbang Crawler

**Files:**
- Modify: `/Users/robin/PycharmProjects/rent_radar/src/crawlers/zigbang.py`
- Modify: `/Users/robin/PycharmProjects/rent_radar/tests/test_zigbang_crawler.py`

**Step 1: Add retry config defaults and metrics fields**

```python
DEFAULT_MAX_RETRIES: Final = 4
DEFAULT_BASE_DELAY_SECONDS: Final = 1.0
DEFAULT_MAX_BACKOFF_SECONDS: Final = 12.0
DEFAULT_COOLDOWN_SECONDS: Final = 20.0
DEFAULT_COOLDOWN_THRESHOLD: Final = 3
```

**Step 2: Add shared request helper with retry policy**

```python
async def _request_json_with_retry(self, client: httpx.AsyncClient, url: str) -> dict[str, object] | None:
    ...
```

**Step 3: Route `_search_by_region_name` and `_fetch_item_details` through helper**

```python
payload = await self._request_json_with_retry(client, search_url)
if not payload:
    return []
```

**Step 4: Re-run crawler tests**

Run: `uv run pytest /Users/robin/PycharmProjects/rent_radar/tests/test_zigbang_crawler.py -q`
Expected: PASS including new 429 tests.

**Step 5: Commit implementation**

```bash
git add /Users/robin/PycharmProjects/rent_radar/src/crawlers/zigbang.py /Users/robin/PycharmProjects/rent_radar/tests/test_zigbang_crawler.py
git commit -m "feat: add balanced retry and cooldown policy for zigbang crawler"
```

### Task 3: Add Failing Tests for One-Shot Live Crawl Prep Script

**Files:**
- Create: `/Users/robin/PycharmProjects/rent_radar/tests/test_manual_prepare_mcp_live_data.py`

**Step 1: Add args parsing contract test**

```python
def test_parse_args_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    ...
    assert args.region_codes == "41135"
```

**Step 2: Add run-flow test with monkeypatched crawler/upsert**

```python
@pytest.mark.anyio
async def test_run_reports_success_with_upserted_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    ...
    assert report["status"] == "success"
```

**Step 3: Add failure test when crawl returns zero/upsert zero**

```python
@pytest.mark.anyio
async def test_run_reports_failure_when_no_rows_persisted(monkeypatch: pytest.MonkeyPatch) -> None:
    ...
    assert "upsert_count <= 0" in report["failures"]
```

**Step 4: Run script-test file first**

Run: `uv run pytest /Users/robin/PycharmProjects/rent_radar/tests/test_manual_prepare_mcp_live_data.py -q`
Expected: FAIL because script module does not exist yet.

**Step 5: Commit test scaffold**

```bash
git add /Users/robin/PycharmProjects/rent_radar/tests/test_manual_prepare_mcp_live_data.py
git commit -m "test: define one-shot live crawl prep script contract"
```

### Task 4: Implement One-Shot Live Crawl Prep Script (Non-Destructive)

**Files:**
- Create: `/Users/robin/PycharmProjects/rent_radar/scripts/manual_prepare_mcp_live_data.py`
- Modify: `/Users/robin/PycharmProjects/rent_radar/tests/test_manual_prepare_mcp_live_data.py`

**Step 1: Implement CLI args and validation**

```python
@dataclass(frozen=True)
class CliArgs:
    region_codes: str
    property_types: str
    max_regions: int
```

**Step 2: Implement crawl -> upsert -> report flow**

```python
crawler = ZigbangCrawler(region_names=region_names, property_types=property_types, ...)
crawl_result = await crawler.run()
upsert_count = await upsert_listings(session, crawl_result.rows)
```

**Step 3: Emit strict JSON report with failure list**

```python
report = {
    "status": "success" if not failures else "failure",
    "crawl": {...},
    "persistence": {"upsert_count": upsert_count},
}
```

**Step 4: Run new script tests**

Run: `uv run pytest /Users/robin/PycharmProjects/rent_radar/tests/test_manual_prepare_mcp_live_data.py -q`
Expected: PASS.

**Step 5: Commit script implementation**

```bash
git add /Users/robin/PycharmProjects/rent_radar/scripts/manual_prepare_mcp_live_data.py /Users/robin/PycharmProjects/rent_radar/tests/test_manual_prepare_mcp_live_data.py
git commit -m "feat: add non-destructive live crawl prep script for mcp manual tests"
```

### Task 5: Add Claude Desktop Manual Test Playbook

**Files:**
- Create: `/Users/robin/PycharmProjects/rent_radar/docs/playbooks/claude-desktop-mcp-manual-test.md`
- Modify: `/Users/robin/PycharmProjects/rent_radar/README.md`

**Step 1: Write playbook with preflight and data prep commands**

```markdown
1. Run `uv run python scripts/manual_prepare_mcp_live_data.py --region-codes 41135`
2. Start MCP server: `uv run python -m src.mcp_server.server`
```

**Step 2: Add natural-language prompt checklist**

```markdown
- "분당구 아파트 전세 10개만 보여줘"
- "정자동으로 좁혀서 보증금 5억~8억만 보여줘"
```

**Step 3: Add troubleshooting for 429 and oversized responses**

```markdown
- Increase delay/backoff args
- Reduce regions and narrow query filters
```

**Step 4: Link playbook in README**

```markdown
Manual playbook: `/Users/robin/PycharmProjects/rent_radar/docs/playbooks/claude-desktop-mcp-manual-test.md`
```

**Step 5: Commit docs**

```bash
git add /Users/robin/PycharmProjects/rent_radar/docs/playbooks/claude-desktop-mcp-manual-test.md /Users/robin/PycharmProjects/rent_radar/README.md
git commit -m "docs: add claude desktop mcp manual live-crawl playbook"
```

### Task 6: Verification and Final Integration Commit

**Files:**
- Modify: all files touched in Tasks 1-5

**Step 1: Run focused tests**

Run: `uv run pytest /Users/robin/PycharmProjects/rent_radar/tests/test_zigbang_crawler.py /Users/robin/PycharmProjects/rent_radar/tests/test_manual_prepare_mcp_live_data.py -q`
Expected: PASS.

**Step 2: Run broader MCP regression tests**

Run: `uv run pytest /Users/robin/PycharmProjects/rent_radar/tests/test_mcp_search_rent.py /Users/robin/PycharmProjects/rent_radar/tests/test_mcp_region_tools.py /Users/robin/PycharmProjects/rent_radar/tests/test_mcp_favorite_tools.py -q`
Expected: PASS.

**Step 3: Run lint checks**

Run: `uv run ruff check /Users/robin/PycharmProjects/rent_radar/src/crawlers/zigbang.py /Users/robin/PycharmProjects/rent_radar/scripts/manual_prepare_mcp_live_data.py /Users/robin/PycharmProjects/rent_radar/tests/test_zigbang_crawler.py /Users/robin/PycharmProjects/rent_radar/tests/test_manual_prepare_mcp_live_data.py`
Expected: PASS.

**Step 4: Optional live dry-run (manual environment)**

Run: `uv run python /Users/robin/PycharmProjects/rent_radar/scripts/manual_prepare_mcp_live_data.py --region-codes 41135 --property-types 아파트`
Expected: JSON output with `status` and non-negative `crawl.count` / `persistence.upsert_count`.

**Step 5: Final commit**

```bash
git add -A
git commit -m "feat: support manual claude desktop mcp testing with live crawl prep"
```
