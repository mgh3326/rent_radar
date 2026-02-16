# Claude Desktop MCP Live-Crawl Manual Test Design

Date: 2026-02-16
Branch: `main`
Status: Approved design capture

## 1) Background

We need a practical way to test MCP tools with real crawl data by asking natural language questions in Claude Desktop.

Current gaps:
- Existing deterministic seed scripts do not validate live crawl behavior.
- Existing live crawl e2e script is destructive (`full` reset), which is too risky for routine local checks.
- Zigbang crawl currently has limited HTTP retry control, so repeated manual runs can hit `429` rate limits.

## 2) Goals and Non-Goals

### Goals

1. Add a non-destructive one-shot helper flow for live Zigbang crawl + DB upsert + MCP readiness checks.
2. Add a Claude Desktop manual test playbook with concrete natural language prompts and expected checks.
3. Introduce balanced 429 prevention/retry behavior suitable for local manual testing.

### Non-Goals

1. No MCP contract-runner expansion in this phase.
2. No `run_id` isolation mode.
3. No automatic post-run cleanup/delete for local data.
4. No `listings -> real_trades` fallback behavior in MCP tools.

## 3) Selected Approach

### Considered options

1. Seed-only manual test flow.
2. One-shot live crawl helper script + manual playbook. (selected)
3. Full automation via contract runner + CI pipeline.

### Why option 2

It gives realistic data-path validation while keeping execution control with the operator. It avoids overbuilding CI scope and matches the decision to keep actual Claude Desktop testing manual.

## 4) Architecture and Components

### A. Zigbang crawler retry hardening

Update `src/crawlers/zigbang.py` to support:
- Base pacing between calls.
- Retry on `429` and selected `5xx`.
- Exponential backoff with jitter.
- Cooldown after repeated `429`.
- Run metrics for retry/cooldown observability.

### B. One-shot live data prep script

Add `scripts/manual_prepare_mcp_live_data.py` that:
- Resolves region names from region codes.
- Runs `ZigbangCrawler` with explicit retry/pacing options.
- Upserts into `listings` using existing repository flow.
- Does not delete existing rows by default.
- Prints JSON report (counts, failures, timings, retry metrics).

### C. Claude Desktop manual playbook

Add `docs/playbooks/claude-desktop-mcp-manual-test.md` that defines:
- Environment preflight.
- Data prep command.
- Claude Desktop MCP configuration and startup check.
- Natural-language prompt scenarios (`search_regions`, `search_rent`, favorite flow).
- Expected result checks and troubleshooting guide.

## 5) Data and Execution Flow

1. Operator runs one-shot script with target region(s) (example: `41135`).
2. Script crawls Zigbang with retry/pacing, then upserts listings.
3. Operator starts MCP server and connects Claude Desktop.
4. Operator executes playbook prompts in natural language.
5. Operator validates `search_rent` quality with filtered queries to avoid oversized responses.

Data retention policy:
- Keep crawled data locally.
- If reset is needed, operator uses explicit DB cleanup command manually.

## 6) 429 Prevention Policy (Balanced)

1. Always apply base request delay.
2. On `429` or retryable `5xx`, retry with capped exponential backoff + jitter.
3. After repeated `429`, apply cooldown window before continuing.
4. Stop after max retries and record failure details in report.
5. Expose retry/cooldown metrics for manual tuning.

## 7) Error Handling and Operator UX

Script JSON result contract:
- `status`: `success` or `failure`
- `crawl`: `count`, `errors`, retry/cooldown counters
- `persistence`: `upsert_count`
- `failures`: explicit failure codes when any check fails

Playbook guidance:
- How to reduce request pressure (fewer regions/property types) when 429 persists.
- How to narrow MCP query (`region_code`, `dong`, `property_type`, `limit`) to avoid oversized responses.

## 8) Acceptance Criteria

1. New helper script runs without destructive full reset.
2. Crawler applies configured retry/backoff/cooldown on `429` and retryable `5xx`.
3. Manual playbook exists at `docs/playbooks/claude-desktop-mcp-manual-test.md`.
4. Playbook includes real prompts and expected checks for Claude Desktop MCP usage.
5. Targeted tests for crawler retry behavior and helper-script flow pass.

## 9) Risks and Mitigations

1. Risk: persistent 429 during peak time.
Mitigation: lower scope (`region_codes`, `property_types`) and increase base delay/cooldown.

2. Risk: large MCP responses reduce usability.
Mitigation: playbook enforces constrained query patterns and explicit `limit`.

3. Risk: stale local data over time.
Mitigation: keep manual DB reset procedure in playbook and run prep script before each session.
