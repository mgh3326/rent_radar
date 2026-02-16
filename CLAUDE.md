# CLAUDE.md — Rent Radar 프로젝트 가이드

## 프로젝트 개요

직방(Zigbang) 매물 데이터 수집 및 MCP 질의를 제공하는 시스템. FastAPI + TaskIQ + PostgreSQL 기반으로 구성되며, 런타임 표면은 Zigbang 중심으로 유지된다.

## 기술 스택

- **언어**: Python 3.12
- **패키지 관리**: uv
- **웹 프레임워크**: FastAPI + Uvicorn
- **ORM**: SQLAlchemy 2.0 (async) + asyncpg
- **DB**: PostgreSQL 16
- **캐시/큐**: Redis 7 + TaskIQ
- **마이그레이션**: Alembic
- **HTTP 클라이언트**: httpx
- **설정 관리**: pydantic-settings
- **AI 통합**: MCP (Model Context Protocol)
- **테스트**: pytest + pytest-anyio
- **컨테이너**: Docker Compose

## 프로젝트 구조

```
src/
├── config/settings.py        # 환경 변수 로딩 (Pydantic Settings)
├── models/
│   ├── listing.py            # 매물 테이블
│   ├── favorite.py           # 관심 매물 테이블
│   └── price_change.py       # 가격 변동 이력 테이블
├── db/
│   ├── session.py            # 비동기 DB 세션 관리
│   └── repositories.py       # 데이터 접근 레이어 (upsert, 조회, 집계)
├── crawlers/
│   ├── base.py               # 크롤러 베이스 정의
│   └── zigbang.py            # 직방 API 크롤러
├── taskiq_app/
│   ├── broker.py             # Redis 브로커 + 스케줄러 설정
│   ├── tasks.py              # 백그라운드 태스크 (crawl_zigbang_listings, monitor_favorites)
│   ├── worker.py             # 워커 진입점
│   └── dedup.py              # Redis 기반 중복 실행 방지
├── mcp_server/
│   ├── server.py             # MCP 서버 진입점
│   └── tools/                # MCP 도구 (listing/favorite/region)
└── main.py                   # FastAPI 앱 (브로커 라이프사이클 포함)
tests/
├── conftest.py               # 픽스처 (InMemoryBroker, dedup 초기화)
├── test_tasks.py             # 태스크 단위 테스트
└── test_mcp_*.py             # MCP 도구 단위/계약 테스트
```

## 빌드 및 실행

### 의존성 설치

```bash
uv sync --extra dev
```

### Docker Compose로 실행 (권장)

```bash
docker compose up -d
```

서비스 포트:
- API: `localhost:8001` (Swagger: `localhost:8001/docs`)
- PostgreSQL: `localhost:5433` (user: rent / password: rent_password / db: rent_finder)
- Redis: `localhost:6380`

### 로컬 실행 (Docker 없이)

```bash
cp .env.example .env
alembic upgrade head
uvicorn src.main:app --reload --port 8001
```

## 테스트

```bash
uv run pytest -q
uv run pytest tests/test_tasks.py tests/test_web_router_qa.py -q
uv run pytest tests/test_mcp_allowlist.py tests/test_mcp_region_tools.py tests/test_mcp_favorite_tools.py tests/test_e2e_zigbang_mcp_tool_suite.py -q
```

테스트 환경에서는 `TASKIQ_TESTING=true`로 InMemoryBroker가 사용된다.

## 환경 변수 (.env)

핵심 변수:
- `DATABASE_URL` — PostgreSQL 비동기 연결 문자열
- `REDIS_URL` — Redis 연결 URL
- `MCP_ENABLED_TOOLS` — MCP 허용 도구 목록 (미설정/빈 값이면 전체 활성)

권장 MCP allowlist:

```dotenv
MCP_ENABLED_TOOLS=search_rent,list_regions,search_regions,add_favorite,list_favorites,remove_favorite,manage_favorites
```

보조 변수:
- `TARGET_PROPERTY_TYPES` — 수집 대상 매물유형 (기본: apt)
- `TARGET_REGION_CODES` — 수집 대상 지역코드 (기본: 11110)
- `LISTING_CACHE_TTL_SECONDS` — 매물 조회 캐시 TTL
- `CRAWL_DEDUP_TTL_SECONDS` — 태스크 dedup 락 TTL

`PUBLIC_DATA_*` 변수는 레거시 호환용이며 Zigbang-only 런타임에서는 사용하지 않는다.

## 주요 컨벤션

- **비동기 우선**: DB 세션, HTTP 요청, 태스크 모두 async/await 사용
- **Repository 패턴**: `src/db/repositories.py`에서 모든 DB 쿼리 처리
- **Upsert 전략**: `ON CONFLICT DO NOTHING`으로 중복 데이터 무시
- **Dedup 락**: Redis 기반 분산 락으로 태스크 중복 실행 방지
- **스케줄링**:
  - `crawl_zigbang_listings`: 6시간마다 (`30 */6 * * *`)
  - `monitor_favorites`: 12시간마다 (`0 */12 * * *`)

## MCP 도구 범위

- `search_rent`
- `list_regions`, `search_regions`
- `add_favorite`, `remove_favorite`, `list_favorites`, `manage_favorites`

## 브랜치 전략

- `main` — 메인 브랜치 (PR 대상)
- 작업 브랜치에서 개발 후 main으로 PR 생성
