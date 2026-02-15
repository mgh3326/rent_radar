# Rent Radar MCP Roadmap Checklist

Last Updated: 2026-02-15

## Checklist Rules
- `[ ]` Not started
- `[x]` Completed
- For each completed item, add one evidence line with command/report/test result.

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

## Stage 4 (Pending) - Naver single e2e
- [ ] Add `e2e_naver_mcp_check.py`
- [ ] Add source-only cleanup + seed validation
- [ ] Validate `--mcp-limit 3` and `--mcp-limit 1` cases

## Stage 5 (Pending) - MCP Tool Coverage
- [ ] Add contract tests for region/favorite/compare tools
- [ ] Validate boundary inputs and error-response contracts

## Stage 6 (Pending) - Live Smoke & Runbook
- [ ] Add Zigbang fail-fast live smoke
- [ ] Add Naver 429/retry smoke
- [ ] Document operation checklist/runbook

## Stage Completion Criteria
- Stage is complete only when:
  - 100% of its child checkboxes are marked `[x]`
  - At least one evidence entry exists in `Execution Log`

## Execution Log
| Date | Stage/Item | Evidence |
|---|---|---|
| 2026-02-15 | Stage 2 baseline verification | `test_mcp_search_rent.py: 6 passed`, `e2e_mcp_search_rent_check.py: status=success` |
| 2026-02-15 | Stage 3 MCP allowlist | `test_mcp_allowlist.py: 5 passed`, `test_mcp_search_rent.py: 6 passed`, docs/env/checklist updated |
| 2026-02-15 | Stage 3 final verification refresh | `uv run pytest tests/test_mcp_allowlist.py -q: 7 passed`, `uv run pytest tests/test_mcp_search_rent.py -q: 6 passed`, `uv run ruff check ...: All checks passed` |
