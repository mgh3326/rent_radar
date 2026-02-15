# Rent Radar MCP Roadmap Checklist

Last Updated: 2026-02-15

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
  - `compare_listings` (market fields may be `None`/`0` when no real_trade data)
- Deferred from Stage 4:
  - `get_real_price`, `get_price_trend` (real_trades dependency)
  - `check_jeonse_safety` (sale_trades dependency)
- Recommended runtime allowlist (`.env`):
  - `MCP_ENABLED_TOOLS=search_rent,list_regions,search_regions,add_favorite,list_favorites,remove_favorite,manage_favorites,compare_listings`

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
- [x] Add MCP contract tests for region/favorite/compare tools
  - Evidence: `uv run pytest /Users/robin/PycharmProjects/rent_radar/tests/test_mcp_region_tools.py -q` -> `4 passed`, `uv run pytest /Users/robin/PycharmProjects/rent_radar/tests/test_mcp_favorite_tools.py -q` -> `7 passed`, `uv run pytest /Users/robin/PycharmProjects/rent_radar/tests/test_mcp_compare_listings.py -q` -> `5 passed`.
- [x] Add Zigbang seed-based MCP integrated e2e (`search_rent` -> `favorite` -> `compare`)
  - Evidence: `uv run python /Users/robin/PycharmProjects/rent_radar/scripts/e2e_zigbang_mcp_tool_suite.py --cleanup-scope source_only --mcp-limit 3` -> `status=success`.
- [x] Validate boundary/error contracts (`listing not found`, compare `1`/`11`, `invalid action`)
  - Evidence: `uv run pytest /Users/robin/PycharmProjects/rent_radar/tests/test_e2e_zigbang_mcp_tool_suite.py -q` -> `10 passed` and e2e JSON `contract_checks` contains `listing_not_found`, `compare_one`, `compare_eleven`, `invalid_action`.
- [x] Add README guide section for Zigbang-only MCP operation
  - Evidence: `/Users/robin/PycharmProjects/rent_radar/README.md` adds `Zigbang-Only MCP Tool Suite Verification (Stage 4)` with allowlist, commands, and success criteria including `market_avg_deposit`/`market_sample_count` `None`/`0` acceptance.
- [x] Add e2e preflight fail-fast + boundary contract regression hardening
  - Evidence: `/Users/robin/PycharmProjects/rent_radar/scripts/e2e_zigbang_mcp_tool_suite.py` adds `_assert_required_tools_available()` preflight before DB cleanup/upsert and `/Users/robin/PycharmProjects/rent_radar/tests/test_e2e_zigbang_mcp_tool_suite.py` adds contract drift tests for `listing_not_found`, `compare_one`, `compare_eleven` and required-tool preflight failure.
- [x] Add seed/e2e evidence entries in Execution Log
  - Evidence: Stage 4 dated rows added under `Execution Log`.

## Stage 5 (Pending) - Zigbang Live Smoke & Runbook
- [ ] Add `crawl_zigbang_listings` live smoke (`ok` or `schema_mismatch` contract)
- [ ] Re-verify blank `source_id` fail-fast before upsert
- [ ] Document Zigbang operation runbook (failure interpretation + action)
- [ ] Add dated live evidence entries

## Stage 6 (TODO) - Naver Crawl & 429 Hardening (Deferred)
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
- `uv run pytest /Users/robin/PycharmProjects/rent_radar/tests/test_mcp_compare_listings.py -q`
- `uv run python /Users/robin/PycharmProjects/rent_radar/scripts/e2e_zigbang_mcp_tool_suite.py --cleanup-scope source_only --mcp-limit 3`
- `uv run ruff check /Users/robin/PycharmProjects/rent_radar/scripts/e2e_zigbang_mcp_tool_suite.py /Users/robin/PycharmProjects/rent_radar/tests/test_mcp_region_tools.py /Users/robin/PycharmProjects/rent_radar/tests/test_mcp_favorite_tools.py /Users/robin/PycharmProjects/rent_radar/tests/test_mcp_compare_listings.py /Users/robin/PycharmProjects/rent_radar/tests/test_e2e_zigbang_mcp_tool_suite.py`

## Execution Log

### Active Roadmap Evidence
| Date | Stage/Item | Evidence |
|---|---|---|
| 2026-02-15 | Stage 2 baseline verification | `test_mcp_search_rent.py: 6 passed`, `e2e_mcp_search_rent_check.py: status=success` |
| 2026-02-15 | Stage 3 MCP allowlist | `test_mcp_allowlist.py: 5 passed`, `test_mcp_search_rent.py: 6 passed`, docs/env/checklist updated |
| 2026-02-15 | Stage 3 final verification refresh | `uv run pytest tests/test_mcp_allowlist.py -q: 7 passed`, `uv run pytest tests/test_mcp_search_rent.py -q: 6 passed`, `uv run ruff check ...: All checks passed` |
| 2026-02-15 | Stage 4 Zigbang-first MCP contract tests (baseline before hardening) | `uv run pytest tests/test_mcp_region_tools.py -q: 4 passed`, `uv run pytest tests/test_mcp_favorite_tools.py -q: 7 passed`, `uv run pytest tests/test_mcp_compare_listings.py -q: 5 passed`, `uv run pytest tests/test_e2e_zigbang_mcp_tool_suite.py -q: 6 passed` |
| 2026-02-15 | Stage 4 Zigbang seed integrated e2e | `uv run python scripts/e2e_zigbang_mcp_tool_suite.py --cleanup-scope source_only --mcp-limit 3` -> `status=success` |
| 2026-02-15 | Stage 4 static checks and docs refresh | `uv run ruff check scripts/e2e_zigbang_mcp_tool_suite.py tests/test_mcp_region_tools.py tests/test_mcp_favorite_tools.py tests/test_mcp_compare_listings.py tests/test_e2e_zigbang_mcp_tool_suite.py` -> `All checks passed`, README/.env/checklist Stage 4 section updated |
| 2026-02-15 | Stage 4 preflight + contract regression hardening | `uv run pytest tests/test_e2e_zigbang_mcp_tool_suite.py -q: 10 passed` (required-tool preflight + listing_not_found/compare_one/compare_eleven drift checks), `uv run ruff check ...` -> `All checks passed` |

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
