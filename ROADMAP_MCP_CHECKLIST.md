# Rent Radar MCP Roadmap Checklist

Last Updated: 2026-02-17

## Checklist Rules
- `[ ]` Not started
- `[x]` Completed
- For each completed item, add one evidence line with command/report/test result.

## Rebase Decision (2026-02-15)
- Priority re-aligned to **Zigbang-first MCP coverage**.
- Stage 4 is now defined as: MCP completeness and reliability using Zigbang data only.
- Naver crawl quality improvement (including 429 hardening) is deferred to Stage 6 TODO.

## Stage 4 Scope (Zigbang-only)
- Supported MCP tools:
  - `search_rent`
  - `list_regions`, `search_regions`
  - `add_favorite`, `list_favorites`, `remove_favorite`, `manage_favorites`
- Hard-deleted surface (2026-02-16):
  - `get_real_price`, `get_price_trend`
  - `check_jeonse_safety`
  - `compare_listings`
  - Naver/public-data crawler & task/web paths
- Recommended runtime allowlist (`.env`):
  - `MCP_ENABLED_TOOLS=search_rent,list_regions,search_regions,add_favorite,list_favorites,remove_favorite,manage_favorites`

## Stage 2 (Completed)
- [x] `search_rent` seed-based e2e script implemented
  - Evidence: `uv run python /Users/robin/PycharmProjects/rent_radar/scripts/e2e_mcp_search_rent_check.py --cleanup-scope source_only --mcp-limit 3` -> `status=success`
- [x] MCP contract tests (6 tests) passed
  - Evidence: `uv run pytest /Users/robin/PycharmProjects/rent_radar/tests/test_mcp_search_rent.py -q` -> `6 passed`
- [x] README MCP verification section updated
  - Evidence: `/Users/robin/PycharmProjects/rent_radar/README.md` includes `MCP search_rent Verification (Source-Only Seed)`
- [x] Verification command set passed
  - Evidence: `tests/test_zigbang_crawler.py` (`6 passed`), `tests/test_tasks.py tests/test_web_router_qa.py` (`12 passed`)

## Stage 3 (Completed) - MCP Allowlist
- [x] Add `MCP_ENABLED_TOOLS` configuration
  - Evidence: `/Users/robin/PycharmProjects/rent_radar/src/config/settings.py` adds `mcp_enabled_tools` parsing/normalization and `/Users/robin/PycharmProjects/rent_radar/.env.example` documents usage.
- [x] Apply registration filter in `server.py`
  - Evidence: `/Users/robin/PycharmProjects/rent_radar/src/mcp_server/server.py` adds `create_mcp_server()` with allowlist validation + `mcp.remove_tool(...)` filtering.
- [x] Add allowlist on/off tests
  - Evidence: `uv run pytest /Users/robin/PycharmProjects/rent_radar/tests/test_mcp_allowlist.py -q` -> `7 passed`.
- [x] Update README operation guide for allowlist
  - Evidence: `/Users/robin/PycharmProjects/rent_radar/README.md` includes `MCP_ENABLED_TOOLS` default/partial/fail-fast behavior.

## Stage 4 (Completed) - Zigbang-first MCP Coverage
- [x] Zigbang-only runtime profile documented (`MCP_ENABLED_TOOLS` based)
  - Evidence: `/Users/robin/PycharmProjects/rent_radar/.env.example` adds Stage 4 Zigbang-only allowlist example and `/Users/robin/PycharmProjects/rent_radar/README.md` includes the same runtime profile.
- [x] Add MCP contract tests for region/favorite tools
  - Evidence: `uv run pytest /Users/robin/PycharmProjects/rent_radar/tests/test_mcp_region_tools.py -q` -> `4 passed`, `uv run pytest /Users/robin/PycharmProjects/rent_radar/tests/test_mcp_favorite_tools.py -q` -> `7 passed`.
- [x] Add Zigbang seed-based MCP integrated e2e (`search_rent` -> `favorite`)
  - Evidence: `uv run python /Users/robin/PycharmProjects/rent_radar/scripts/e2e_zigbang_mcp_tool_suite.py --cleanup-scope source_only --mcp-limit 3` -> `status=success`.
- [x] Validate boundary/error contracts (`listing not found`, `invalid action`)
  - Evidence: `uv run pytest /Users/robin/PycharmProjects/rent_radar/tests/test_e2e_zigbang_mcp_tool_suite.py -q` -> `7 passed` and e2e JSON `contract_checks` contains `listing_not_found`, `invalid_action`.
- [x] Add README guide section for Zigbang-only MCP operation
  - Evidence: `/Users/robin/PycharmProjects/rent_radar/README.md` adds `Zigbang-Only MCP Tool Suite Verification (Stage 4)` with allowlist, commands, and success criteria including `market_avg_deposit`/`market_sample_count` `None`/`0` acceptance.
- [x] Add e2e preflight fail-fast + boundary contract regression hardening
  - Evidence: `/Users/robin/PycharmProjects/rent_radar/scripts/e2e_zigbang_mcp_tool_suite.py` adds `_assert_required_tools_available()` preflight before DB cleanup/upsert and `/Users/robin/PycharmProjects/rent_radar/tests/test_e2e_zigbang_mcp_tool_suite.py` adds contract drift tests for `listing_not_found`, `invalid_action` and required-tool preflight failure.
- [x] Add seed/e2e evidence entries in Execution Log
  - Evidence: Stage 4 dated rows added under `Execution Log`.

## Stage 5 (Completed) - Zigbang Live Smoke & Runbook
- [x] Add `crawl_zigbang_listings` live smoke (`ok` or `schema_mismatch` contract)
  - Evidence: `uv run python scripts/smoke_zigbang_live_crawl.py --fingerprint stage5-smoke-20260216` -> `result=success`, `status=ok`.
- [x] Re-verify blank `source_id` fail-fast before upsert
  - Evidence: `uv run pytest tests/test_tasks.py::test_crawl_zigbang_schema_mismatch_fails_before_upsert -q` -> `1 passed`, `uv run pytest tests/test_zigbang_crawler.py -q` -> `15 passed`.
- [x] Document Zigbang operation runbook (failure interpretation + action)
  - Evidence: `docs/playbooks/claude-desktop-mcp-manual-test.md` adds `Stage 5 Live Smoke (Local Manual)` with success/failure interpretation and action hints.
- [x] Add dated live evidence entries
  - Evidence: Stage 5 dated row added under `Execution Log`.

## Stage 6 - Naver Crawl & 429 Hardening

### Phase 1 (Observer-Only)
- [x] Add Naver 429 observer runner with first-429 fail-fast contract
  - Evidence: `uv run python scripts/observe_naver_429.py --region-codes 11680 --property-types APT --max-regions 1 --requests-per-region 5 --fingerprint stage6-observe-20260217` -> `status=rate_limited`, `summary.attempted_requests=1`, `summary.first_429_at_request_index=1`, `first_429.retry_after=null`.
- [x] Add observer report schema hardening and contract tests
  - Evidence: `uv run python -m pytest tests/test_observe_naver_429.py -q` -> `8 passed`; `uv run ruff check scripts/observe_naver_429.py tests/test_observe_naver_429.py` -> `All checks passed!`.

### Phase 2 (Deferred)
- [ ] Implement 429 policy (`Retry-After` first, fallback to exponential backoff + jitter)
- [ ] Add request throttling strategy for region/property/trade loops
- [ ] Define degraded status threshold + notification criteria
- [ ] Verify live success acceptance (`inserted > 0`) with dated evidence
- [ ] Add Naver smoke test and runbook

## Stage Completion Criteria
- Stage is complete only when:
  - 100% of its child checkboxes are marked `[x]`
  - At least one evidence entry exists in `Execution Log`

## Verification Commands (Stage 4 Target)
- `uv run pytest /Users/robin/PycharmProjects/rent_radar/tests/test_mcp_region_tools.py -q`
- `uv run pytest /Users/robin/PycharmProjects/rent_radar/tests/test_mcp_favorite_tools.py -q`
- `uv run python /Users/robin/PycharmProjects/rent_radar/scripts/e2e_zigbang_mcp_tool_suite.py --cleanup-scope source_only --mcp-limit 3`
- `uv run ruff check /Users/robin/PycharmProjects/rent_radar/scripts/e2e_zigbang_mcp_tool_suite.py /Users/robin/PycharmProjects/rent_radar/tests/test_mcp_region_tools.py /Users/robin/PycharmProjects/rent_radar/tests/test_mcp_favorite_tools.py /Users/robin/PycharmProjects/rent_radar/tests/test_e2e_zigbang_mcp_tool_suite.py`

## Execution Log

### Active Roadmap Evidence
| Date | Stage/Item | Evidence |
|---|---|---|
| 2026-02-17 | Stage 6 phase-1 observer verification | `uv run python scripts/observe_naver_429.py --region-codes 11680 --property-types APT --max-regions 1 --requests-per-region 5 --fingerprint stage6-observe-20260217` -> `status=rate_limited`, `attempted_requests=1`, `first_429_at_request_index=1`, `retry_after=null`; `uv run python -m pytest tests/test_observe_naver_429.py -q` -> `8 passed`; `uv run ruff check scripts/observe_naver_429.py tests/test_observe_naver_429.py` -> `All checks passed!` |
| 2026-02-16 | Archive baseline before hard delete | Archive branch: `archive/pre-zigbang-hard-delete-2026-02-16`, Archive tag: `archive-zigbang-hard-delete-base-2026-02-16` |
| 2026-02-16 | Zigbang-only hard-delete verification | `uv run ruff check src tests scripts` -> `All checks passed`, retained suite `42 passed`, `uv run python scripts/e2e_zigbang_mcp_tool_suite.py --cleanup-scope source_only --mcp-limit 3` -> `status=success` |
| 2026-02-16 | Stage 5 zigbang live smoke and verification refresh | `uv run python scripts/smoke_zigbang_live_crawl.py --fingerprint stage5-smoke-20260216` -> `result=success`, `status=ok`; `uv run pytest tests/test_smoke_zigbang_live_crawl.py tests/test_tasks.py tests/test_zigbang_crawler.py -q` -> `24 passed`; `uv run ruff check scripts/smoke_zigbang_live_crawl.py tests/test_smoke_zigbang_live_crawl.py tests/test_tasks.py` -> `All checks passed` |
| 2026-02-15 | Stage 2 baseline verification | `test_mcp_search_rent.py: 6 passed`, `e2e_mcp_search_rent_check.py: status=success` |
| 2026-02-15 | Stage 3 MCP allowlist | `test_mcp_allowlist.py: 5 passed`, `test_mcp_search_rent.py: 6 passed`, docs/env/checklist updated |
| 2026-02-15 | Stage 3 final verification refresh | `uv run pytest tests/test_mcp_allowlist.py -q: 7 passed`, `uv run pytest tests/test_mcp_search_rent.py -q: 6 passed`, `uv run ruff check ...: All checks passed` |
| 2026-02-15 | Stage 4 Zigbang-first MCP contract tests (baseline before hardening) | `uv run pytest tests/test_mcp_region_tools.py -q: 4 passed`, `uv run pytest tests/test_mcp_favorite_tools.py -q: 7 passed`, `uv run pytest tests/test_e2e_zigbang_mcp_tool_suite.py -q: 6 passed` |
| 2026-02-15 | Stage 4 Zigbang seed integrated e2e | `uv run python scripts/e2e_zigbang_mcp_tool_suite.py --cleanup-scope source_only --mcp-limit 3` -> `status=success` |
| 2026-02-15 | Stage 4 static checks and docs refresh | `uv run ruff check scripts/e2e_zigbang_mcp_tool_suite.py tests/test_mcp_region_tools.py tests/test_mcp_favorite_tools.py tests/test_e2e_zigbang_mcp_tool_suite.py` -> `All checks passed`, README/.env/checklist Stage 4 section updated |
| 2026-02-15 | Stage 4 preflight + contract regression hardening | `uv run pytest tests/test_e2e_zigbang_mcp_tool_suite.py -q: 7 passed` (required-tool preflight + listing_not_found/invalid_action drift checks), `uv run ruff check ...` -> `All checks passed` |

### Archived / Deferred (Naver Track)
| Date | Stage/Item | Evidence |
|---|---|---|
| 2026-02-15 | Legacy Stage 4 (Seed-only) Naver single e2e (`--mcp-limit 3`) | `jq`: `success/0/3/3`; fallback `python -c`: `success 0 3 3` |
| 2026-02-15 | Legacy Stage 4 (Seed-only) Naver single e2e (`--mcp-limit 1`) | `jq`: `success/1/1/1`; fallback `python -c`: `success 1 1 1` |
| 2026-02-15 | Legacy Stage 4 Naver script regression tests | `uv run pytest /Users/robin/PycharmProjects/rent_radar/tests/test_e2e_naver_mcp_check.py -q: 8 passed` |
| 2026-02-15 | Legacy Stage 4-1 runtime image timestamp check | `docker inspect -f '{{.Config.Image}} {{.Created}}' rent-radar-worker rent-radar-scheduler` -> `rent-radar-worker 2026-02-08...`, `rent-radar-scheduler 2026-02-07...` |
| 2026-02-15 | Legacy Stage 4-1 429 degraded status verification (local task codepath) | `uv run python -c ... crawl_naver_listings.original_func()` -> `status=degraded_rate_limited`, `fetched=0`, `errors_count=8`, `429_count=8` |
| 2026-02-15 | Legacy Stage 4-1 DB state check after live call | `uv run python -c ... Listing(source='naver') count` -> `naver_total=0 naver_active=0` |
| 2026-02-15 | Legacy Stage 4-1 Zigbang schema guard/status verification | `uv run python -c ... crawl_zigbang_listings.original_func()` -> `status=schema_mismatch`, `errors_count=1`; `uv run pytest tests/test_tasks.py tests/test_naver_crawler.py -q` includes blank `source_id` guard test |
| TBD | Legacy Stage 4-1 Naver live crawl success (`inserted > 0`) | Deferred to Stage 6 |
