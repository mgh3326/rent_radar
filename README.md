# Rent Radar

공공주택 임대료 정보 수집 및 분석 시스템

## Features

- MOLIT (국토교통부) 공동주택 임대료 데이터 수집
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
- `PUBLIC_DATA_API_KEY`: 공공데이터포털 API Key (필수, 없으면 mock 데이터 사용)
- `TARGET_REGION_CODES`: 대상 지역 코드 (기본: 11110 - 종로구)
- `TARGET_PROPERTY_TYPES`: 매물 유형 (apt, villa, officetel)
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`: 텔레그램 알림용

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
- `search_rent` - 임대 매물 검색 (캐시 적용)
- `get_real_price` - 실거래가 조회
- `get_price_trend` - 가격 추이
- `check_jeonse_safety` - 전세 안전성 진단
- `compare_listings` - 매물 비교
- `get_price_trend` - 지역별 가격 추이
- `manage_favorites` - 관심매물 관리
- `list_regions`, `search_regions` - 지역 정보

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

- **crawl_real_trade**: 매일 03:00 UTC (12:00 KST)
- **crawl_naver_listings**: 6시간마다 (0 */6)
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
