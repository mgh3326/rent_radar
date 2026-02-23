# Zigbang Crawl Freshness MCP Design (`search_rent` Extension)

Date: 2026-02-20
Owner: rent_radar
Status: Implemented

## 1. Goal

Extend MCP `search_rent` response with region-level crawl freshness status for `source="zigbang"`, without changing read-only behavior or existing response contract fields.

## 2. Scope and Non-Goals

Scope:
- Add `crawl_status` to every `search_rent` response.
- Add optional `crawl_message` only when `crawl_status.needs_crawl == true`.
- Evaluate freshness by region-level Zigbang data presence and staleness (`48h`).
- Re-evaluate freshness on every call, including cache-hit paths.

Non-goals:
- No automatic enqueue from MCP tool.
- No crawler/task scheduler changes.
- No change to existing `query/count/items/cache_hit/message` semantics.

## 3. Response Contract

New fields in `search_rent` response:
- `crawl_status: dict`
- `crawl_message: str` (present only when `needs_crawl=true`)

`crawl_status` schema:
- `source`: `"zigbang"`
- `region_code`: `str | null`
- `evaluated`: `bool`
- `needs_crawl`: `bool | null`
- `reason`: `"fresh_data" | "stale_data" | "no_region_data" | "no_region_filter" | "invalid_region_code"`
- `last_seen_at`: `ISO8601 str | null`
- `stale_threshold_hours`: `48`

## 4. Decision Rules

Input: `region_code`, fixed `source="zigbang"`, fixed threshold `48h`

Rule order:
1. `region_code` is missing/blank:
   - `evaluated=false`, `needs_crawl=null`, `reason="no_region_filter"`
2. `region_code` invalid:
   - `evaluated=false`, `needs_crawl=null`, `reason="invalid_region_code"`
3. Region-level Zigbang total count is `0`:
   - `evaluated=true`, `needs_crawl=true`, `reason="no_region_data"`
4. Region-level `last_seen_at` older than `now - 48h`:
   - `evaluated=true`, `needs_crawl=true`, `reason="stale_data"`
5. Otherwise:
   - `evaluated=true`, `needs_crawl=false`, `reason="fresh_data"`

## 5. Architecture Changes

### Repository (`src/db/repositories.py`)
- Extracted reusable region predicate builder from `fetch_listings` region logic.
- Added aggregate API for freshness:
  - input: `region_code`, `source`
  - output: `total_count`, `max(last_seen_at)`
- Defensive behavior for missing/invalid region code: empty summary (`0`, `null`).

### Service (`src/services/listing_service.py`)
- Added `evaluate_crawl_status(region_code, stale_hours=48, source="zigbang")`.
- Performs input normalization/validation and calls repository freshness aggregate.
- Returns normalized status payload with deterministic `reason` values.

### MCP Tool (`src/mcp_server/tools/listing.py`)
- Always includes `crawl_status` in response.
- Cache hit:
  - keeps cached `items` payload behavior
  - re-evaluates `crawl_status` in real time
- Adds `crawl_message` only when `needs_crawl=true`.

## 6. Cache Semantics

- Listing search result payload (`items`, `count`) remains cache-based for performance.
- Freshness status is recomputed on every call for timeliness.
- This avoids stale freshness decisions while preserving cache efficiency for listing content.

## 7. Test Strategy

MCP contract tests (`tests/test_mcp_search_rent.py`):
- no region code
- invalid region code
- no region data
- stale data
- fresh data
- cache-hit re-evaluation of `crawl_status`

Service tests (`tests/test_listing_service.py`):
- no region / invalid region branches
- no data / stale / fresh branches
- fixed `stale_threshold_hours=48` and default source behavior

Regression invariants preserved:
- `count == len(items)`
- cache miss/hit behavior for listing payload
- empty result `message` behavior
