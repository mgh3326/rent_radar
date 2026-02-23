# Zigbang Crawl Freshness MCP Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add region-level Zigbang crawl freshness metadata to `search_rent` responses with deterministic reasons and no side effects.

**Architecture:** Keep cached listing payload behavior intact while recomputing `crawl_status` every call. Compute freshness in service using repository aggregation (`COUNT`, `MAX(last_seen_at)`) with shared region predicate logic.

**Tech Stack:** Python 3.12, FastAPI/MCP, SQLAlchemy async ORM, pytest(anyio), ruff, pyright

---

## Task 1: Add repository freshness aggregate and reusable region predicate

**Files**
- Modify: `src/db/repositories.py`
- Verify: `tests/test_listing_service.py`

**Steps**
1. Extract `fetch_listings` region filtering expression into reusable internal helper.
2. Add aggregate method for region/source freshness summary:
   - `total_count = COUNT(listings.id)`
   - `last_seen_at = MAX(listings.last_seen_at)`
3. Add defensive empty return for missing/invalid `region_code` at repository level.
4. Reuse helper in `fetch_listings` to keep filter behavior identical.

## Task 2: Implement service-level crawl status evaluator

**Files**
- Modify: `src/services/listing_service.py`
- Verify: `tests/test_listing_service.py`

**Steps**
1. Add `evaluate_crawl_status(region_code, stale_hours=48, source="zigbang")`.
2. Implement fixed branching rules:
   - missing/blank region -> `no_region_filter`
   - invalid region -> `invalid_region_code`
   - count 0 -> `no_region_data`
   - stale (`last_seen_at < now - 48h`) -> `stale_data`
   - else -> `fresh_data`
3. Return schema-compatible dict with `stale_threshold_hours=48`.

## Task 3: Integrate `crawl_status` into MCP `search_rent`

**Files**
- Modify: `src/mcp_server/tools/listing.py`
- Verify: `tests/test_mcp_search_rent.py`

**Steps**
1. Add constants for source (`zigbang`) and stale threshold (`48`).
2. Add status evaluation call on both cache miss and cache hit paths.
3. Always include `crawl_status` in response.
4. Add `crawl_message` only when `needs_crawl=true`.
5. Keep existing empty-result `message` behavior and existing response fields untouched.

## Task 4: Expand contract and branching tests

**Files**
- Modify: `tests/test_mcp_search_rent.py`
- Modify: `tests/test_listing_service.py`

**Steps**
1. Add MCP test cases for:
   - no region filter
   - invalid region code
   - no region data
   - stale data
   - fresh data
   - cache-hit status re-evaluation
2. Add service tests for all branch reasons and threshold default behavior.
3. Preserve existing regression assertions for count/cache/message invariants.

## Task 5: Verification and quality gate

**Commands**
- `uv run pytest tests/test_mcp_search_rent.py -q`
- `uv run pytest tests/test_listing_service.py -q`
- `uv run ruff check src/mcp_server/tools/listing.py src/services/listing_service.py src/db/repositories.py tests/test_mcp_search_rent.py tests/test_listing_service.py`
- `uv run pyright src/mcp_server/tools/listing.py src/services/listing_service.py src/db/repositories.py`

**Expected**
- All target tests pass.
- No lint/type errors in touched files.
- `search_rent` contract preserved with added freshness metadata.
