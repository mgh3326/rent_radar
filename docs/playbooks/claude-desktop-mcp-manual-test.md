# Claude Desktop MCP Manual Live-Crawl Playbook

## Scope

Manual verification flow for Claude Desktop + MCP with live Zigbang crawl and non-destructive upsert.

## Preflight

1. Ensure PostgreSQL and Redis are reachable from your local environment.
2. Confirm `.env` is configured for `DATABASE_URL`, `REDIS_URL`, and optional `MCP_ENABLED_TOOLS`.
3. Use a narrow region/property scope first to reduce API throttling risk.

## Prepare Live Data

Run one-shot crawl and persistence:

```bash
uv run python scripts/manual_prepare_mcp_live_data.py --region-codes 41135 --property-types 아파트
```

Expected output:
- JSON only
- `status` is either `success` or `failure`
- `crawl.count` is non-negative
- `persistence.upsert_count` is non-negative

Retry policy in this script:
- Retry targets: `429`, `500`, `502`, `503`, `504`
- Backoff: exponential + jitter
- Cooldown: applied on repeated `429`
- `--base-delay-seconds` affects both normal request cadence and retry backoff baseline

## Start MCP Server

```bash
uv run python -m src.mcp_server.server
```

Keep this process running while testing in Claude Desktop.

## Claude Desktop Manual Prompt Checklist

Use the prompts below in order:

1. `분당구 아파트 전세 10개만 보여줘`
2. `정자동으로 좁혀서 보증금 5억~8억만 보여줘`
3. `같은 조건으로 다시 조회해서 캐시 히트 여부도 알려줘`
4. `분당구 정자동 아파트 전세, 보증금 5억~8억, 10개만 보여줘`

Manual pass criteria:
- Tool call completes without server errors
- Returned count matches item length
- Filters (`dong`, deposit range, property type) are reflected in results

## Troubleshooting

### Repeated 429 from Zigbang

Increase retry pacing in the prep script:

```bash
uv run python scripts/manual_prepare_mcp_live_data.py --region-codes 41135 --property-types 아파트 --max-retries 6 --base-delay-seconds 1.5 --max-backoff-seconds 20 --cooldown-seconds 30 --cooldown-threshold 2
```

Also reduce scope:
- Keep `--max-regions 1`
- Use one property type at a time

### Oversized MCP responses or slow tool calls

- Lower request limit in natural language prompt (for example, 5 or 10)
- Narrow by `dong` and deposit range first
- Avoid broad all-region queries during manual checks
