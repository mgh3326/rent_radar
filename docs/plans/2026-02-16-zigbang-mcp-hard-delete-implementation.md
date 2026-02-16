# Zigbang-Only Hard-Delete Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reduce `main` to an intentional Zigbang-only product surface by removing Naver/public-data and their dependent MCP/UI/test/doc paths, while preserving an archive recovery point.

**Architecture:** Keep only Zigbang listing ingestion plus listing/favorite/region MCP tools. Remove Naver/public-data crawlers, their task/web entry points, and public-data-dependent MCP tools. Keep future recovery via archive branch/tag, not dormant runtime paths.

**Tech Stack:** FastAPI, TaskIQ, SQLAlchemy async, MCP FastMCP, pytest, ruff, Python 3.12.

---

### Task 1: Create Archive Baseline Before Deletion

**Files:**
- Modify: `ROADMAP_MCP_CHECKLIST.md`

**Step 1: Add archive placeholders to roadmap (failing doc expectation first)**

```markdown
| 2026-02-16 | Archive baseline before hard delete | branch/tag to be filled after creation |
```

**Step 2: Verify roadmap change is visible**

Run: `git diff -- ROADMAP_MCP_CHECKLIST.md`
Expected: diff includes an archive evidence row placeholder.

**Step 3: Create archive branch and tag**

```bash
git branch archive/pre-zigbang-hard-delete-2026-02-16
git tag archive-zigbang-hard-delete-base-2026-02-16
```

**Step 4: Update roadmap with concrete archive refs**

```markdown
Archive branch: archive/pre-zigbang-hard-delete-2026-02-16
Archive tag: archive-zigbang-hard-delete-base-2026-02-16
```

**Step 5: Commit**

```bash
git add ROADMAP_MCP_CHECKLIST.md
git commit -m "chore: record archive baseline for zigbang hard-delete"
```

### Task 2: Remove Public-Data and Compare/Safety/Price MCP Surface

**Files:**
- Delete: `src/mcp_server/tools/price.py`
- Delete: `src/mcp_server/tools/safety.py`
- Delete: `src/mcp_server/tools/comparison.py`
- Modify: `src/mcp_server/server.py`
- Modify: `tests/test_mcp_allowlist.py`
- Delete: `tests/test_mcp_price_tools.py`
- Delete: `tests/test_mcp_compare_listings.py`
- Delete: `tests/test_safety_service.py`

**Step 1: Write failing MCP registry test for reduced tool set**

```python
ALL_TOOL_NAMES = {
    "add_favorite",
    "list_favorites",
    "list_regions",
    "manage_favorites",
    "remove_favorite",
    "search_rent",
    "search_regions",
}
```

**Step 2: Run test to verify it fails before code update**

Run: `uv run pytest tests/test_mcp_allowlist.py::test_allowlist_off_registers_all_tools -q`
Expected: FAIL because removed tools are still registered.

**Step 3: Remove tool registrations and deleted-tool imports**

```python
TOOL_REGISTRATIONS = (
    (register_listing_tools, ("search_rent",)),
    (register_region_tools, ("list_regions", "search_regions")),
    (register_favorite_tools, ("add_favorite", "list_favorites", "remove_favorite", "manage_favorites")),
)
```

**Step 4: Delete removed MCP tool tests and module files**

```bash
git rm src/mcp_server/tools/price.py src/mcp_server/tools/safety.py src/mcp_server/tools/comparison.py
git rm tests/test_mcp_price_tools.py tests/test_mcp_compare_listings.py tests/test_safety_service.py
```

**Step 5: Run MCP tests**

Run: `uv run pytest tests/test_mcp_allowlist.py tests/test_mcp_region_tools.py tests/test_mcp_favorite_tools.py -q`
Expected: PASS.

**Step 6: Commit**

```bash
git add src/mcp_server/server.py tests/test_mcp_allowlist.py
git commit -m "refactor: keep zigbang-only mcp tool surface"
```

### Task 3: Remove Naver/Public-Data Crawler and Task Entry Points

**Files:**
- Delete: `src/crawlers/naver.py`
- Delete: `src/crawlers/public_api.py`
- Modify: `src/crawlers/__init__.py`
- Modify: `src/taskiq_app/tasks.py`
- Modify: `src/web/router.py`
- Delete: `tests/test_naver_crawler.py`
- Modify: `tests/test_tasks.py`
- Modify: `tests/test_web_router_qa.py`

**Step 1: Write failing task tests against removed symbols**

```python
from src.taskiq_app.tasks import crawl_zigbang_listings, enqueue_crawl_zigbang_listings
```

**Step 2: Run targeted tests to confirm current imports still include removed domains**

Run: `uv run pytest tests/test_tasks.py -q`
Expected: FAIL on outdated public-data/naver expectations.

**Step 3: Remove Naver/public-data task functions and imports**

```python
# keep only zigbang listing crawl + favorite monitor task paths
```

**Step 4: Remove corresponding web trigger endpoints**

```python
# remove /web/crawl and naver/all branches from /web/crawl-listings
```

**Step 5: Delete obsolete crawler file/tests and update remaining tests**

```bash
git rm src/crawlers/naver.py src/crawlers/public_api.py tests/test_naver_crawler.py
```

**Step 6: Run task/web tests**

Run: `uv run pytest tests/test_tasks.py tests/test_web_router_qa.py -q`
Expected: PASS with zigbang-only behavior.

**Step 7: Commit**

```bash
git add src/crawlers/__init__.py src/taskiq_app/tasks.py src/web/router.py tests/test_tasks.py tests/test_web_router_qa.py
git commit -m "refactor: remove naver and public-data task paths"
```

### Task 4: Remove Public-Data/Price Dashboard Dependencies from Web UX

**Files:**
- Modify: `src/web/router.py`
- Modify: `src/web/templates/base.html`
- Modify: `src/web/templates/listings.html`
- Modify: `src/web/templates/qa.html`
- Modify: `src/web/templates/dashboard.html`

**Step 1: Write failing route expectations for reduced UX scope**

```python
assert "/web/crawl" not in rendered_html
assert "네이버" not in rendered_html
```

**Step 2: Run focused web tests to capture mismatch**

Run: `uv run pytest tests/test_web_router_qa.py -q`
Expected: FAIL due old form/actions/source options.

**Step 3: Implement minimal template/router changes**

```html
<option value="zigbang" selected>직방</option>
```

```python
# remove public-data dashboard data fetches (PriceService calls)
```

**Step 4: Re-run web tests**

Run: `uv run pytest tests/test_web_router_qa.py -q`
Expected: PASS for zigbang-only UI paths.

**Step 5: Commit**

```bash
git add src/web/router.py src/web/templates/base.html src/web/templates/listings.html src/web/templates/qa.html src/web/templates/dashboard.html tests/test_web_router_qa.py
git commit -m "refactor: simplify web ui to zigbang-only flows"
```

### Task 5: Remove/Refactor Scripts and E2E Contracts to Match New Scope

**Files:**
- Delete: `scripts/e2e_naver_mcp_check.py`
- Delete: `tests/test_e2e_naver_mcp_check.py`
- Modify: `scripts/e2e_zigbang_mcp_tool_suite.py`
- Modify: `tests/test_e2e_zigbang_mcp_tool_suite.py`

**Step 1: Write failing e2e contract expectations for no-compare scope**

```python
assert "compare_listings" not in required_tools
```

**Step 2: Run zigbang e2e unit tests and confirm mismatch**

Run: `uv run pytest tests/test_e2e_zigbang_mcp_tool_suite.py -q`
Expected: FAIL because compare checks are still required.

**Step 3: Remove compare contract path from script/tests**

```python
_REQUIRED_STAGE4_TOOLS = (
    "search_rent",
    "add_favorite",
    "list_favorites",
    "manage_favorites",
)
```

**Step 4: Delete obsolete naver script/tests**

```bash
git rm scripts/e2e_naver_mcp_check.py tests/test_e2e_naver_mcp_check.py
```

**Step 5: Re-run e2e-related tests**

Run: `uv run pytest tests/test_e2e_zigbang_mcp_tool_suite.py -q`
Expected: PASS for zigbang-only contract.

**Step 6: Commit**

```bash
git add scripts/e2e_zigbang_mcp_tool_suite.py tests/test_e2e_zigbang_mcp_tool_suite.py
git commit -m "test: align zigbang e2e contracts with hard-delete scope"
```

### Task 6: Update Settings/Docs/Checklist for Hard-Delete Scope

**Files:**
- Modify: `.env.example`
- Modify: `README.md`
- Modify: `ROADMAP_MCP_CHECKLIST.md`
- Modify: `CLAUDE.md`

**Step 1: Write failing docs checklist expectations**

```markdown
- MCP tools list excludes compare/price/safety tools
- No Naver/public-data runtime instructions in active path
```

**Step 2: Update `.env.example` allowlist examples**

```dotenv
MCP_ENABLED_TOOLS=search_rent,list_regions,search_regions,add_favorite,list_favorites,remove_favorite,manage_favorites
```

**Step 3: Rewrite README and roadmap sections to new scope**

```markdown
Phase-1 supports Zigbang-only MCP listing and favorite workflows.
```

**Step 4: Run markdown/docs sanity check**

Run: `uv run python -m compileall src tests scripts`
Expected: PASS (no import breakage from deleted modules).

**Step 5: Commit**

```bash
git add .env.example README.md ROADMAP_MCP_CHECKLIST.md CLAUDE.md
git commit -m "docs: document zigbang-only hard-delete scope"
```

### Task 7: Full Verification and Final Integration Commit

**Files:**
- Modify: any remaining touched files from prior tasks

**Step 1: Run lints**

Run: `uv run ruff check src tests scripts`
Expected: PASS.

**Step 2: Run retained-scope test suite**

Run: `uv run pytest tests/test_mcp_allowlist.py tests/test_mcp_region_tools.py tests/test_mcp_favorite_tools.py tests/test_mcp_search_rent.py tests/test_tasks.py tests/test_web_router_qa.py tests/test_e2e_zigbang_mcp_tool_suite.py -q`
Expected: PASS.

**Step 3: Run retained zigbang e2e script**

Run: `uv run python scripts/e2e_zigbang_mcp_tool_suite.py --cleanup-scope source_only --mcp-limit 3`
Expected: JSON `status=success`.

**Step 4: Final commit**

```bash
git add -A
git commit -m "refactor: hard-delete naver/public-data and keep zigbang-only core"
```

**Step 5: Record final evidence**

```markdown
Add dated verification rows to ROADMAP_MCP_CHECKLIST.md Execution Log.
```
