# Zigbang-Only MCP Scope Redesign (Hard Delete + Archive)

Date: 2026-02-16
Branch: `main`
Status: Draft for execution planning

## 1) Background

The current codebase mixes three data-source tracks:

- Zigbang listing crawl
- Naver listing crawl
- Public-data real-trade crawl

MCP support also spans listing features and public-data-derived features. The immediate product direction is to simplify and run a deliberate Zigbang-first scope. The prior Naver/public-data paths are unstable for current goals (Naver rate-limit concerns and public-data contract mismatch risk), and current feature direction is not yet settled.

Therefore, phase-1 will use a **hard-delete policy in `main`** for Naver/public-data functionality, while preserving a recoverable archive point.

## 2) Goals and Non-Goals

### Goals

1. Keep only intentional, Zigbang-based MCP capabilities in `main`.
2. Remove unstable or undefined feature surfaces to reduce maintenance and ambiguity.
3. Leave a clean archive point for possible future reintroduction.
4. Keep runtime behavior and tests aligned with the reduced scope.

### Non-Goals

1. Do not redesign Naver/public-data integrations now.
2. Do not create speculative replacement features now.
3. Do not keep deprecated paths behind UI toggles/flags in `main`.

## 3) Option Analysis

### Option A: Domain hard-delete + archive (selected)

- Remove Naver/public-data runtime, MCP, UI, tests, scripts, and docs from `main`.
- Preserve a dedicated archive branch/tag before deletion.

Pros: clean codebase, low ambiguity, YAGNI-friendly, easier ownership.
Cons: future reintroduction requires explicit new design/implementation.

### Option B: Runtime disable only

- Keep all code; disable via allowlist/flags.

Pros: quick rollback.
Cons: stale surfaces persist, ongoing maintenance burden, mixed signals.

### Option C: Partial delete (exposed paths only)

- Remove MCP/UI exposure but keep internal modules.

Pros: moderate effort.
Cons: hidden coupling remains; future confusion likely.

## 4) Final Scope Definition

### Keep in phase-1 (`main`)

- Zigbang crawler pipeline.
- Region discovery tools.
- Listing search and favorite management over Zigbang-backed listings.

Target MCP set:

- `search_rent`
- `list_regions`
- `search_regions`
- `add_favorite`
- `list_favorites`
- `remove_favorite`
- `manage_favorites`

### Delete from phase-1 (`main`)

- Naver crawler path and task entry points.
- Public-data crawler path and task entry points.
- MCP tools dependent on public-data:
  - `get_real_price`
  - `get_price_trend`
  - `check_jeonse_safety`
- Dashboard/QA surfaces that require or trigger public-data/Naver collection.
- Associated tests/scripts/docs referencing removed behavior.

### Decision on `compare_listings`

`compare_listings` currently depends on market stats backed by `real_trade` data. Under hard-delete scope and strict YAGNI, this feature is **removed in phase-1** and can be redesigned later as either:

1. listing-only comparison, or
2. comparison with a new, explicit market-data strategy.

## 5) Architecture After Deletion

### Runtime architecture

- Data ingestion: Zigbang only.
- Core data table: listings/favorites/price_changes as applicable to retained features.
- MCP: listing + region + favorite tools only.
- Web: listing/favorite flows only (remove public-data dashboard semantics and manual triggers for removed domains).

### Boundary policy

- If a capability requires Naver/public-data assumptions, it is out-of-scope and absent from `main`.
- Reintroduction requires a new design doc and implementation plan, not ad-hoc re-enable.

## 6) Data Flow (Phase-1)

1. Zigbang crawl task runs and upserts listing records.
2. MCP `search_rent` reads listing records.
3. Favorite tools read/write favorites linked to listing IDs.
4. Region tools serve static region map metadata.

No phase-1 flow should read from public-data real-trade pipeline or Naver ingestion.

## 7) Error Handling Strategy

1. Remove error paths tied to deleted domains instead of masking them.
2. Keep fail-fast startup behavior for invalid MCP configuration.
3. Ensure remaining routes/tools return explicit unsupported/unknown behavior only for truly invalid user input, not for removed internals.

## 8) Test Strategy

### Must pass

1. MCP allowlist and retained-tool contracts.
2. Zigbang crawler tests and retained task tests.
3. Listing/favorite/region integration and e2e scripts that remain in scope.

### Must be removed/refactored

1. Naver crawler tests.
2. Public-data-dependent MCP tests.
3. E2E scripts that assume Naver/public-data behavior.

## 9) Documentation and Operations

1. Update README to describe Zigbang-only product surface.
2. Update roadmap checklist to reflect hard-delete policy and archive pointer.
3. Remove or rewrite QA/dashboard copy that implies public-data baseline ownership.

## 10) Archive Policy

Before any deletion merge:

1. Create archive branch (example: `archive/pre-zigbang-hard-delete-2026-02-16`).
2. Create archive tag (example: `archive-zigbang-hard-delete-base-2026-02-16`).
3. Record branch/tag in roadmap for future recovery reference.

The archive is the sole recovery baseline; `main` stays intentionally clean.

## 11) Risks and Mitigations

### Risk: future requirements need removed capabilities soon

Mitigation: archive branch/tag plus explicit reintroduction plan template.

### Risk: hidden coupling breaks retained features

Mitigation: run focused retained-scope test suite and remove dangling imports/usages.

### Risk: user confusion from old docs/scripts

Mitigation: remove/rename deprecated scripts and rewrite docs in the same change set.

## 12) Acceptance Criteria

1. `main` contains no runtime path that imports or executes Naver/public-data crawlers.
2. Removed MCP tools are absent from registry and tests.
3. Web routes/templates no longer expose removed manual crawl flows.
4. Retained Zigbang MCP flows pass tests and e2e checks.
5. Archive branch/tag exists and is documented.

## 13) Execution Note

Implementation should proceed through a dedicated execution plan that enumerates file-level deletions, refactors, verification commands, and rollback references.
