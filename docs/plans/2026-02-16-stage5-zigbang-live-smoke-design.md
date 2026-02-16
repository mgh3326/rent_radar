# Stage 5 Zigbang Live Smoke Design

Date: 2026-02-16
Owner: Codex + robin
Status: Approved

## 1. Background

Stage 4 (Zigbang-first MCP coverage) is complete. The next priority is Stage 5:

1. Add a live smoke for `crawl_zigbang_listings` with a stable contract.
2. Re-verify blank `source_id` fail-fast behavior.
3. Document operation runbook with failure interpretation and action.
4. Add dated live evidence entries.

This design intentionally targets local manual execution only (not Docker automation).

## 2. Goals and Non-Goals

Goals:
- Provide a dedicated live smoke entrypoint for `crawl_zigbang_listings`.
- Define contract: smoke is successful when crawl status is `ok` or `schema_mismatch`.
- Preserve fail-fast safety by keeping blank `source_id` guard regression checks in verification.
- Document reproducible runbook and evidence logging format for Stage 5 closure.

Non-goals:
- No scheduler or cron changes.
- No Stage 6 Naver/429 hardening work.
- No Docker-only orchestration for smoke in this stage.

## 3. Approach Options Considered

Option A (selected): Add a dedicated Stage 5 smoke script.
- Pros: clear ownership, minimal coupling, explicit contract boundary, easy checklist mapping.
- Cons: one extra script file.

Option B: Add smoke mode into `manual_prepare_mcp_live_data.py`.
- Pros: fewer entrypoints.
- Cons: mixed responsibilities (data prep vs smoke judgment), harder runbook readability.

Option C: Live pytest only.
- Pros: test-native.
- Cons: more flaky in external API conditions, less suitable as operational smoke runbook.

Decision: Option A.

## 4. Architecture

Add one script:
- `scripts/smoke_zigbang_live_crawl.py`

Primary behavior:
- Execute the Zigbang crawl task path used in operations.
- Emit JSON-only output for deterministic interpretation.
- Normalize outcomes into Stage 5 smoke contract.

Contract:
- Success statuses: `ok`, `schema_mismatch`
- Failure statuses: all others, including `skipped_duplicate_execution` and unhandled errors

## 5. Components and Data Flow

Input:
- `--fingerprint` (default `manual-smoke`) to control dedup scope.
- optional `--allow-duplicate-run` to bypass strict dedup failure policy if needed for manual rerun scenarios.

Flow:
1. Start run metadata (`executed_at`, command input).
2. Trigger `crawl_zigbang_listings`.
3. Parse task result dictionary fields (`status`, `fetched`, `count`, `deactivated`).
4. Classify:
   - `ok` -> pass
   - `schema_mismatch` -> pass with action hint
   - `skipped_duplicate_execution` -> fail (crawl did not run)
   - other/exception -> fail
5. Print report JSON and set exit code.

Output schema (minimum):
- `status`
- `executed_at`
- `source`
- `fetched`
- `inserted`
- `deactivated`
- `reason`
- `action_hint`

Exit code:
- `0`: status in `{ok, schema_mismatch}`
- `1`: all other outcomes

## 6. Error Handling Policy

`schema_mismatch`:
- Treated as smoke success for Stage 5 contract.
- Must include `action_hint` requiring immediate parser/schema review with metrics sample.

`skipped_duplicate_execution`:
- Treated as failure for smoke contract.
- Include remediation: wait for dedup TTL or rerun with distinct fingerprint.

Unhandled exception:
- Treated as failure.
- Include concise exception type/message in `reason`.

## 7. Verification Strategy

Stage 5 verification command set:
1. Live smoke run command for local manual execution.
2. Regression tests re-validating blank `source_id` fail-fast and schema mismatch guards:
   - `tests/test_zigbang_crawler.py`
   - `tests/test_tasks.py`
3. Lint/static checks for new script and touched docs/tests.

Pass criteria:
- Live smoke returns `status=ok` or `status=schema_mismatch`.
- Regression tests pass without weakening guard behavior.
- Checklist evidence entries added with date, command, and key output fields.

## 8. Runbook and Evidence Updates

Update:
- `docs/playbooks/claude-desktop-mcp-manual-test.md`:
  - Add "Stage 5 Live Smoke" section.
  - Add failure interpretation table and action rules.

- `ROADMAP_MCP_CHECKLIST.md`:
  - Mark Stage 5 items with dated evidence lines after verification.

Evidence format:
- Date
- Command
- Result summary (`status`, `fetched`, `inserted`, notable warnings/failures)

## 9. Approved Decisions

Confirmed with user:
1. Stage 5 first.
2. Live smoke uses real Zigbang API.
3. Execution baseline is local manual run.
4. Smoke success contract is `status in {ok, schema_mismatch}`.
