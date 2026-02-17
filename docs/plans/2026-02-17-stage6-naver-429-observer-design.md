# Stage 6 Naver 429 Observer Design (Phase 1)

Date: 2026-02-17  
Owner: Codex + robin  
Status: Approved

## 1. Background

Stage 5 (Zigbang live smoke) is complete. The remaining roadmap work is Stage 6, focused on Naver crawl rate-limit handling.

Current branch intentionally removed Naver crawl task paths, so Phase 1 is designed as a non-invasive observation step to collect clean evidence about when 429 occurs.

## 2. Goals and Non-Goals

Goals:
- Add a local manual observer runner for Naver live requests.
- Treat the first `429` as immediate failure and stop the entire run.
- Record failure context in deterministic JSON for follow-up bypass strategy design.
- Keep DB and MCP runtime behavior unchanged in Phase 1.

Non-goals:
- No Naver task-path restoration in this phase.
- No retry/backoff bypass logic in this phase.
- No Docker-first operation requirement (local manual baseline only).
- No response-shape extension such as `source_breakdown`.

## 3. Options Considered

Option A (selected): standalone observer script
- Add `scripts/observe_naver_429.py` only.
- Pros: minimal blast radius, fast iteration, zero impact to current Zigbang-first operation.
- Cons: some logic may later be moved/refactored when formal Naver task path is restored.

Option B: add crawler module + script wrapper
- Pros: stronger reuse path into future task implementation.
- Cons: larger scope than needed for immediate observation objective.

Option C: dual-client experiment (`httpx` + `curl_cffi`) in Phase 1
- Pros: early signal on transport/fingerprint effects.
- Cons: adds complexity and dependency churn before baseline evidence exists.

Decision: Option A.

## 4. Architecture

Add:
- `scripts/observe_naver_429.py`

Execution model:
1. Parse CLI args for region/property scope.
2. Execute live Naver requests in narrow loops.
3. On first `429`, immediately terminate the full run.
4. Emit one JSON report and exit with a contract-based code.

Exit code contract:
- `0`: observation completed with no `429`.
- `1`: first `429` observed (expected fail-fast condition).
- `2`: execution error (network/parsing/unexpected exception).

## 5. Inputs and Output Contract

CLI inputs:
- `--region-codes`: comma-separated region codes.
- `--property-types`: comma-separated property types.
- `--max-regions`: region cap (default small, e.g. 1).
- `--requests-per-region`: per-region request cap (default small, e.g. 5).
- `--timeout-seconds`: request timeout.
- `--fingerprint`: run identifier for evidence correlation.

JSON output (single object):
- `status`: `ok | rate_limited | error`
- `result`: `success | failure`
- `executed_at`: UTC ISO8601
- `fingerprint`
- `summary`:
  - `attempted_requests`
  - `regions_attempted`
  - `first_429_at_request_index` (nullable)
- `first_429` (nullable object):
  - `region_code`
  - `property_type`
  - `request_index`
  - `http_status`
  - `retry_after` (if present)
  - `response_headers_subset` (rate-limit relevant headers only)
- `action_hint`

## 6. Data Flow and Error Policy

Flow:
1. Validate args (`max_regions >= 1`, `requests_per_region >= 1`).
2. Build `(region_code, property_type)` targets.
3. Issue requests sequentially with explicit request index tracking.
4. Branch on response:
   - `200`: continue.
   - `429`: mark `rate_limited`, capture context, stop immediately.
   - other `4xx/5xx`: mark `error`, stop.
5. Print JSON report and return exit code.

Policy:
- `429` is not retried in Phase 1. Signal clarity is prioritized over mitigation.
- Any non-429 execution exception is reported as `error`.
- Output remains concise and machine-parsable for evidence log entry.

## 7. MCP and Data Semantics

- The canonical query surface remains `search_rent` over `listings`.
- `items[].source` already exposes source identity to users.
- Cross-source duplicate removal is out of scope for this phase.
- `source_breakdown` will not be added in this phase.

## 8. Test and Verification Strategy

Planned tests:
- `tests/test_observe_naver_429.py`

Core cases:
1. First `429` => immediate stop, `status=rate_limited`, exit `1`.
2. No `429` => `status=ok`, exit `0`.
3. Network/parse exception => `status=error`, exit `2`.
4. `Retry-After` and rate-limit headers are captured when present.

Verification commands (planned):
- `uv run pytest tests/test_observe_naver_429.py -q`
- `uv run python scripts/observe_naver_429.py ...` (local manual evidence run)

## 9. Approved Decisions

Confirmed with user:
1. Stage 6 baseline is local manual execution.
2. `429` should be treated as failure for this investigation phase.
3. The first `429` stops the entire run immediately.
4. Phase 1 scope is observer-only runner (no Naver task-path restoration yet).
5. Keep response simple; do not add `source_breakdown`.
