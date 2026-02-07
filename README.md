# Rent Radar

공공주택 임대료 정보 수집 및 분석 시스템

## Features

- MOLIT (국토교통부) 공동주택 임대료 데이터 수집
- 자동화된 데이터 업데이트 (스케줄러)
- RESTful API
- TaskIQ 기반 비동기 작업 처리

## Installation

### Prerequisites

- Python 3.10+
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
pip install -r requirements.txt
# 또는 uv 사용 시
uv sync
```

3. Set environment variables
```bash
cp .env.example .env
# .env 파일을 편집하여 필요한 설정값 입력
```

**Environment Variables:**
- `DATABASE_URL`: PostgreSQL connection URL (로컬 개발: `postgresql+asyncpg://rent:rent_password@localhost:5432/rent_finder`)
- `REDIS_URL`: Redis connection URL (로컬 개발: `redis://localhost:6379/0`)
- `PUBLIC_DATA_API_KEY`: 공공데이터포털 API Key (필수)
- `TARGET_REGION_CODES`: 대상 지역 코드 (기본: 11110 - 종로구)
- `APP_ENV`: Application environment (local/development/production)

4. Database migration
```bash
alembic upgrade head
```

5. Run application
```bash
uvicorn src.main:app --reload
```

### Docker Compose (Shared Infrastructure)

이 프로젝트는 공용 인프라 (`~/infra`)와 함께 사용해야 합니다.

1. 공용 인프라 시작
```bash
cd ~/infra
docker compose up -d
```

2. 이 프로젝트 시작
```bash
cd ~/PycharmProjects/rent_radar
docker compose up -d
```

3. 서비스 확인
- API: http://localhost:8001
- API Docs: http://localhost:8001/docs
- Worker: 비동기 작업 처리
- Scheduler: 정기 작업 스케줄링

참고: `~/infra/README.md`에서 공용 인프라 상세 설정을 확인하세요.

## API Documentation

실행 중인 서비스의 Swagger UI에서 확인 가능합니다:
- http://localhost:8001/docs

## Development

### Running locally without Docker

1. 공용 인프라 시작
```bash
cd ~/infra
docker compose up -d
```

2. 애플리케이션 실행
```bash
# API
uvicorn src.main:app --reload

# Worker
taskiq worker src.taskiq_app.worker:broker

# Scheduler
python -c 'from src.taskiq_app.broker import scheduler; import asyncio; asyncio.run(scheduler.startup())'
```

### Database Migration

```bash
# 새 마이그레이션 생성
alembic revision --autogenerate -m "description"

# 마이그레이션 적용
alembic upgrade head
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
