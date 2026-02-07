# CLAUDE.md — Rent Radar 프로젝트 가이드

## 프로젝트 개요

공공주택 임대료 정보 수집 및 분석 시스템. 국토교통부(MOLIT) 공공 API에서 아파트 전·월세 실거래 데이터를 수집하고, FastAPI REST API와 MCP 서버를 통해 분석 결과를 제공한다.

## 기술 스택

- **언어**: Python 3.12
- **패키지 관리**: uv
- **웹 프레임워크**: FastAPI + Uvicorn
- **ORM**: SQLAlchemy 2.0 (async) + asyncpg
- **DB**: PostgreSQL 16
- **캐시/큐**: Redis 7 + TaskIQ
- **마이그레이션**: Alembic
- **HTTP 클라이언트**: httpx
- **XML 파싱**: BeautifulSoup4
- **설정 관리**: pydantic-settings
- **AI 통합**: MCP (Model Context Protocol)
- **테스트**: pytest + pytest-anyio
- **컨테이너**: Docker Compose

## 프로젝트 구조

```
src/
├── config/settings.py        # 환경 변수 로딩 (Pydantic Settings)
├── models/
│   ├── base.py               # SQLAlchemy Base
│   ├── listing.py            # 매물 테이블 (향후 웹 스크래핑용)
│   └── real_trade.py         # 실거래 테이블 (공공 API 데이터)
├── db/
│   ├── session.py            # 비동기 DB 세션 관리
│   └── repositories.py       # 데이터 접근 레이어 (upsert, 조회, 집계)
├── crawlers/
│   ├── base.py               # 크롤러 베이스 정의
│   └── public_api.py         # MOLIT 공공 API 크롤러
├── taskiq_app/
│   ├── broker.py             # Redis 브로커 + 스케줄러 설정
│   ├── tasks.py              # 백그라운드 태스크 (crawl_real_trade)
│   ├── worker.py             # 워커 진입점
│   └── dedup.py              # Redis 기반 중복 실행 방지
├── services/
│   └── price_service.py      # 가격 데이터 비즈니스 로직
├── mcp_server/
│   ├── server.py             # MCP 서버 진입점
│   └── tools/price.py        # MCP 도구 (get_real_price, get_price_trend)
└── main.py                   # FastAPI 앱 (브로커 라이프사이클 포함)
tests/
├── conftest.py               # 픽스처 (InMemoryBroker, dedup 초기화)
├── test_tasks.py             # 태스크 단위 테스트
└── test_tools.py             # 서비스 레이어 테스트
alembic/
└── versions/                 # DB 마이그레이션 스크립트
```

## 빌드 및 실행

### 의존성 설치

```bash
uv sync
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
cp .env.example .env          # 환경 변수 설정
alembic upgrade head          # DB 마이그레이션
uvicorn src.main:app --reload --port 8000
```

## 테스트

```bash
pytest            # 전체 테스트
pytest -v         # 상세 출력
pytest tests/test_tasks.py    # 특정 파일만
```

테스트 환경에서는 `TASKIQ_TESTING=true`로 InMemoryBroker가 사용된다. conftest.py에서 자동 설정됨.

## DB 마이그레이션

```bash
alembic upgrade head                          # 최신 마이그레이션 적용
alembic revision --autogenerate -m "설명"     # 새 마이그레이션 생성
alembic downgrade -1                          # 롤백
```

## 환경 변수 (.env)

필수 변수:
- `DATABASE_URL` — PostgreSQL 비동기 연결 문자열
- `REDIS_URL` — Redis 연결 URL
- `PUBLIC_DATA_API_KEY` — data.go.kr API 키 (없으면 mock 데이터 사용)

선택 변수:
- `APP_ENV` — 실행 환경 (local/development/production)
- `TARGET_REGION_CODES` — 수집 대상 지역코드 (쉼표 구분, 기본: 11110 종로구)
- `PUBLIC_DATA_FETCH_MONTHS` — 수집 기간 (1~24개월, 기본: 2)
- `PUBLIC_DATA_REQUEST_TIMEOUT_SECONDS` — API 요청 타임아웃 (기본: 10.0)

## 주요 컨벤션

- **비동기 우선**: DB 세션, HTTP 요청, 태스크 모두 async/await 사용
- **Repository 패턴**: `src/db/repositories.py`에서 모든 DB 쿼리 처리
- **Upsert 전략**: `ON CONFLICT DO NOTHING`으로 중복 데이터 무시
- **Dedup 락**: Redis 기반 분산 락으로 태스크 중복 실행 방지
- **스케줄링**: 매일 03:00 UTC에 `crawl_real_trade` 태스크 자동 실행

## Docker Compose 서비스 구성

| 서비스 | 이미지/빌드 | 역할 |
|---------|-------------|------|
| postgres | postgres:16-alpine | 데이터 저장소 |
| redis | redis:7-alpine | 태스크 큐 + 캐시 |
| api | ./Dockerfile | FastAPI REST API |
| worker | ./Dockerfile | TaskIQ 백그라운드 워커 |
| scheduler | ./Dockerfile | 크론 스케줄러 |

## 브랜치 전략

- `main` — 메인 브랜치 (PR 대상)
- 작업 브랜치에서 개발 후 main으로 PR 생성
