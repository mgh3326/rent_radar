# Stage 6 Naver 429 Hardening Design (Phase 2)

Date: 2026-02-18  
Owner: Codex + robin  
Status: Approved

## 1. Background

Stage 6 Phase 1 introduced an observer-only probe to capture first-429 evidence without changing runtime paths. Phase 2 restores the Naver TaskIQ path and introduces production-grade 429 handling to satisfy roadmap acceptance (`inserted > 0`) while keeping MCP response shape unchanged.

## 2. Goals and Non-Goals

Goals:
- Restore Naver crawl execution path in TaskIQ (`crawl_naver_listings`, enqueue helper).
- Implement 429 policy: `Retry-After` first, otherwise exponential backoff + jitter.
- Add loop throttling for region/property/trade request flow.
- Enforce hard-failure contract on retry exhaustion (`status=error`, no degraded status).
- Add Naver live smoke and runbook/checklist evidence flow.

Non-goals:
- No web-trigger restoration.
- No MCP schema changes (no `source_breakdown`).
- No cross-source dedupe redesign.

## 3. Options Considered

Option A (selected): minimal restoration + Naver-specific policy in restored crawler/task path.
- Pros: smallest blast radius, fastest path to roadmap completion.
- Cons: retry/throttle logic is not fully unified with Zigbang internals.

Option B: observer-script-centered integration.
- Pros: lower initial code volume.
- Cons: weaker production/runtime alignment.

Option C: full shared retry engine refactor.
- Pros: strongest architectural consistency.
- Cons: oversized for Phase 2 scope and higher regression risk.

## 4. Architecture

- Restore `/Users/robin/.codex/worktrees/5539/rent_radar/src/crawlers/naver.py`.
- Restore `crawl_naver_listings` and `enqueue_crawl_naver_listings` in `/Users/robin/.codex/worktrees/5539/rent_radar/src/taskiq_app/tasks.py`.
- Add `/Users/robin/.codex/worktrees/5539/rent_radar/scripts/smoke_naver_live_crawl.py` for Stage 6 acceptance checks.
- Keep dedup lock pattern and notification pattern consistent with existing Zigbang task.
- Status contract:
  - `ok`
  - `skipped_duplicate_execution`
  - `error`

## 5. Data Flow and 429 Policy

1. Iterate sequentially through `region_codes x property_types x trade_types(B1,B2)`.
2. Apply base throttle before each request.
3. Request handling:
   - `200`: parse and continue.
   - `429`: retry path.
   - other non-200: immediate `error`.
4. Retry path:
   - Prefer `Retry-After` header delay.
   - Fallback delay: `base_delay * 2^attempt`.
   - Apply jitter to effective delay.
   - If retry budget exhausted: immediate `error` and stop task.
5. Persist parsed rows via existing upsert semantics; deactivate stale Naver listings on success path.

Failure policy approved by user:
- Repeated 429 with exhausted retries is always hard failure (`error`), never degraded success.

## 6. Testing and Verification

Test targets:
- `/Users/robin/.codex/worktrees/5539/rent_radar/tests/test_naver_crawler.py`
- `/Users/robin/.codex/worktrees/5539/rent_radar/tests/test_tasks.py`
- `/Users/robin/.codex/worktrees/5539/rent_radar/tests/test_smoke_naver_live_crawl.py`

Core coverage:
- `Retry-After` precedence, fallback exponential backoff + jitter.
- Retry exhaustion -> `error`.
- Task dedup behavior, lock release on failure, and enqueue dedup.
- Smoke contract gates on `inserted > 0` for success.

Manual/ops docs:
- Update `/Users/robin/.codex/worktrees/5539/rent_radar/docs/playbooks/claude-desktop-mcp-manual-test.md` with Stage 6 Phase 2 smoke run.
- Update `/Users/robin/.codex/worktrees/5539/rent_radar/ROADMAP_MCP_CHECKLIST.md` Phase 2 checkboxes and execution evidence rows.

## 7. Approved Decisions

1. Phase 2 scope: complete all five deferred checklist items.
2. Restore Naver through TaskIQ path (not observer-only, not full web restore).
3. On repeated 429 exhaustion, return hard `error` (no degraded status).
4. Live acceptance is successful only when `inserted > 0`.
