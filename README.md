# Rent Radar

직방 매물 데이터 수집 및 MCP 기반 질의 시스템

## Features

- 직방(Zigbang) 매물 데이터 수집
- 자동화된 데이터 업데이트 (스케줄러)
- RESTful API
- MCP (Model Context Protocol) 서버 - Claude Desktop 연동
- TaskIQ 기반 비동기 작업 처리

## Installation

### Prerequisites

- Python 3.12+
- Docker & Docker Compose
- PostgreSQL (공용 인프라 사용)
- Redis (공용 인프라 사용)

### Setup

1. Clone repository
```bash
git clone <repository-url>
cd rent_radar
```

2. Install dependencies
```bash
uv sync
```

3. Set environment variables
```bash
cp .env.example .env
```

**Environment Variables:**
- `DATABASE_URL`: PostgreSQL connection URL (로컬: `postgresql+asyncpg://rent:rent_password@localhost:5433/rent_finder`)
- `REDIS_URL`: Redis connection URL (로컬: `redis://localhost:6380/0`)
- `TARGET_REGION_CODES`: 대상 지역 코드 (기본: 11110 - 종로구)
- `TARGET_PROPERTY_TYPES`: 매물 유형 (apt, villa, officetel)
- `MCP_ENABLED_TOOLS`: MCP tool allowlist (콤마 구분, 미설정/빈 값이면 전체 tool 활성)
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`: 텔레그램 알림용
- `PUBLIC_DATA_*`: 레거시 설정 (Zigbang-only 런타임에서는 사용하지 않음)

4. Database migration
```bash
alembic upgrade head
```

5. Run application
```bash
uvicorn src.main:app --reload --port 8001
```

### Docker Compose

```bash
docker compose up -d
```

**Services:**
- API: http://localhost:8001
- API Docs: http://localhost:8001/docs
- Worker: 비동기 작업 처리
- Scheduler: 정기 작업 스케줄링

**Ports:**
- PostgreSQL: 5433
- Redis: 6380
- API: 8001

## MCP Server

Claude Desktop 또는 MCP 클라이언트에서 사용 가능:

**Available Tools:**
- `search_rent` - 임대 매물 검색 (`listings` 기반, 캐시 적용, 0건 시 데이터 소스 안내 메시지 포함)
- `add_favorite`, `remove_favorite`, `list_favorites`, `manage_favorites` - 관심매물 관리
- `list_regions`, `search_regions` - 지역 정보

**Tool Allowlist (`MCP_ENABLED_TOOLS`):**
- 미설정/빈 값: 전체 tool 활성 (기본 동작)
- 일부만 허용: `MCP_ENABLED_TOOLS=search_rent,list_regions`
- 오타/미지원 이름 포함: 서버 시작 시 `ValueError`로 fail-fast

**Claude Desktop 설정:**
```json
{
  "mcpServers": {
    "rent-radar": {
      "command": "uv",
      "args": ["run", "python", "-m", "src.mcp_server.server"]
    }
  }
}
```

## Scheduled Tasks

- **crawl_zigbang_listings**: 6시간마다 (30 */6)
- **monitor_favorites**: 12시간마다 (가격 변동 감지)

## Development

### Running locally

```bash
# API
uvicorn src.main:app --reload --port 8001

# Worker
taskiq worker src.taskiq_app.worker:broker

# Scheduler
taskiq scheduler src.taskiq_app.broker:scheduler
```

### Testing

```bash
uv run pytest -q
```

## Zigbang Crawler Troubleshooting

- `https://apis.zigbang.com/v2/search` can return location/complex metadata (`id/type/name/_source`) instead of listing payloads.
- The crawler now fails fast when `raw_count > 0` but `parsed_count == 0`.
- This fail-fast behavior is expected and prevents polluted data (`source_id=""`) from being inserted.

### Zigbang schema fixture (representative sample)

The regression fixture contains 12 representative items selected for meaningful diversity:
- `tests/fixtures/zigbang_search_jongro_representative.json`

**Selection criteria (non-random, fixed IDs):**
- Type diversity: `address` (1) + `apartment` (11)
- Region diversity (local3): 평창동/무악동/동숭동/창신동/숭인동/신문로2가/교북동/당주동/통인동/익선동
- Value diversity: 오래된/최신 사용승인일 (1966~2025), household 최소/최대 (37~964)

**Metadata preserves:**
- `observed_total_items_raw` / `observed_unique_ids`: capture-time observation snapshot values (can change on refresh)
- `representative_item_ids`: fixed 12 IDs for reproducibility
- `representative_item_count`: fixed to 12

Regression tests validate contract/invariants (`representative IDs` + `observed_total_items_raw >= observed_unique_ids >= representative_item_count`) rather than hardcoding snapshot counts.

To refresh the fixture:

```bash
uv run python scripts/build_zigbang_representative_fixture.py
```

### Regression checks

```bash
uv run pytest tests/test_zigbang_crawler.py -q
uv run pytest tests/test_tasks.py tests/test_web_router_qa.py -q
uv run python scripts/e2e_zigbang_mcp_check.py --reset-scope full --confirm-reset RESET_ALL
```

## MCP `search_rent` Verification (Source-Only Seed)

- Goal: verify `search_rent` tool behavior without crawler/worker dependencies.
- Cleanup policy: delete only seed-source data (`source='zigbang_test_seed'`), not full tables.
- Roadmap checklist: `/Users/robin/PycharmProjects/rent_radar/ROADMAP_MCP_CHECKLIST.md`

### Run

```bash
uv run python /Users/robin/PycharmProjects/rent_radar/scripts/e2e_mcp_search_rent_check.py --cleanup-scope source_only
uv run pytest /Users/robin/PycharmProjects/rent_radar/tests/test_mcp_search_rent.py -q
```

- Shell safety: 명령어 실행 시 `>` 리다이렉션으로 전체 명령 문자열이 파일명으로 저장되지 않도록 주의하세요.

### Success criteria

- First `search_rent` call: `cache_hit=false`
- Second call with same query: `cache_hit=true`
- `count > 0`
- `expected_count=min(3, limit)` and both calls match expected count
- Both calls satisfy `count == len(items)`
- Returned items (first/second call) have non-empty `source_id`
- Returned items (first/second call) satisfy `dong == seed_dong`
- Returned item count does not exceed `limit` in both calls
- Note: script may leave seed rows at process end; next run starts with source-only cleanup.

## Zigbang-Only MCP Tool Suite Verification (Stage 4)

- Goal: validate `search_rent -> add/list favorites` with Zigbang seed rows and fixed error contracts.
- Recommended runtime allowlist:

```bash
MCP_ENABLED_TOOLS=search_rent,list_regions,search_regions,add_favorite,list_favorites,remove_favorite,manage_favorites
```

- Preflight behavior: `scripts/e2e_zigbang_mcp_tool_suite.py` checks MCP tools required by this Stage 4 tool-suite script at startup via `mcp.list_tools()` and fails fast with `RuntimeError` (including recommended `MCP_ENABLED_TOOLS`) before cleanup/upsert if any required tool is missing.

### Run

```bash
uv run pytest /Users/robin/PycharmProjects/rent_radar/tests/test_mcp_region_tools.py -q
uv run pytest /Users/robin/PycharmProjects/rent_radar/tests/test_mcp_favorite_tools.py -q
uv run pytest /Users/robin/PycharmProjects/rent_radar/tests/test_e2e_zigbang_mcp_tool_suite.py -q
uv run python /Users/robin/PycharmProjects/rent_radar/scripts/e2e_zigbang_mcp_tool_suite.py --cleanup-scope source_only --mcp-limit 3
```

### Preflight fail-fast check (repro)

```bash
MCP_ENABLED_TOOLS=search_rent uv run python /Users/robin/PycharmProjects/rent_radar/scripts/e2e_zigbang_mcp_tool_suite.py --cleanup-scope source_only --mcp-limit 3
```

- Expected: immediate `status=failure` with `Required Stage 4 MCP tools are missing before execution: ...`
- Expected: failure happens before cleanup/upsert (no DB mutation from this run)

### Success criteria

- `search_rent` returns `count > 0`, `count == len(items)`, first call `cache_hit=false`, second call `cache_hit=true`
- `add_favorite` succeeds for seeded listing and `list_favorites` satisfies `count == len(items)`
- Error contracts are fixed by tests: `listing not found`, `manage_favorites(action="invalid")`
- Missing required Stage 4 tools causes immediate preflight failure before DB operations (fail-fast, deterministic env contract)

## 수동 시드 기반 MCP 지역검증

- 목적: 워커/스케줄러를 돌리지 않고 `list_regions` / `search_rent(region_code=...)` 지역 필터 동작을 재현 검증
- 기준 지역코드:
  - `11110`: 서울특별시 종로구
  - `11680`: 서울특별시 강남구
  - `41135`: 경기도 성남시분당구
- 캐시 주의사항: `search_rent`는 Redis 캐시(TTL 기본 1800초)를 사용하므로, 빈 결과가 캐시되면 수동 검증 시 false negative가 발생할 수 있음

### Run (seed -> check)

```bash
uv run python /Users/robin/PycharmProjects/rent_radar/scripts/manual_seed_mcp_region_test_data.py --cleanup-source-only --clear-cache
uv run python /Users/robin/PycharmProjects/rent_radar/scripts/manual_mcp_region_checks.py --limit 20
```

- `manual_seed_mcp_region_test_data.py`는 `source=manual_test_seed` 데이터만 정리/재시드하고, 검증에 사용하는 `region_code + property_type=apt` 캐시 키를 함께 삭제
- `11680`은 강남구 시드로 지역 필터를 검증

## Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│    API      │────▶│   Worker    │────▶│   Redis     │
└─────────────┘     └─────────────┘     └─────────────┘
       │                                        │
       └────────────────────────────────────────┘
                         │
                   ┌─────────────┐
                   │  PostgreSQL  │
                   └─────────────┘
```

## License

MIT
