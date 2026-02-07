# PROJECT KNOWLEDGE BASE

**Generated:** 2026-02-07
**Branch:** main

## OVERVIEW
Public housing rent data collection and analysis system using FastAPI + TaskIQ + PostgreSQL. Crawls Korean MOLIT public API and serves data via REST API and MCP (Model Context Protocol).

## STRUCTURE
```
./
├── alembic/              # DB migrations
├── docker-entrypoint-initdb.d/  # PostgreSQL init scripts
├── src/
│   ├── config/          # Pydantic settings
│   ├── crawlers/        # Public API scrapers
│   ├── db/              # Repository layer + session management
│   ├── mcp_server/      # MCP protocol server
│   ├── models/          # SQLAlchemy models
│   ├── services/        # Business logic
│   └── taskiq_app/      # Async task queue (Redis/InMemoryBroker)
├── tests/               # pytest with InMemoryBroker
├── docker-compose.yml   # 5 services: postgres, redis, api, worker, scheduler
├── pyproject.toml       # uv dependencies
└── alembic.ini          # Alembic config
```

## WHERE TO LOOK
| Task | Location | Notes |
|------|----------|-------|
| FastAPI entrypoint | src/main.py | lifespan manages broker lifecycle |
| Async task definitions | src/taskiq_app/tasks.py | scheduled cron: 0 3 * * * |
| DB queries | src/db/repositories.py | repository pattern, upsert semantics |
| MCP tools | src/mcp_server/tools/ | price queries for model context |
| Crawler logic | src/crawlers/public_api.py | MOLIT public API integration |
| Schema migrations | alembic/versions/ | Alembic revision scripts |
| Environment config | .env / pyproject.toml | Settings via Pydantic |

## CONVENTIONS
**Async-first**: All DB calls, HTTP requests, tasks use async/await
**Repository pattern**: src/db/repositories.py handles all DB operations
**Upsert semantics**: PostgreSQL `ON CONFLICT DO NOTHING` for duplicate-safe inserts
**Redis dedup**: Prevents task re-execution via `SET NX EX` locks
**TaskIQ testing**: `TASKIQ_TESTING=true` uses InMemoryBroker
**Service separation**: src/services/ for business logic, src/db/ for data access

## ANTI-PATTERNS (THIS PROJECT)
- NEVER run tasks synchronously in API routes
- NEVER use SQLAlchemy sync sessions
- NEVER skip broker.startup() in API lifespan (non-worker processes)
- NEVER commit migrations manually in production (docker-compose handles it)
- NEVER use `await session.execute()` without proper session context manager

## UNIQUE STYLES
**Docker Compose multi-process**: Separate containers for api/worker/scheduler sharing same image
**Broker detection**: `broker.is_worker_process` flag prevents double-initialization
**Dedup pattern**: Two-phase lock (enqueue + execution) prevents race conditions
**Repository dataclasses**: `@dataclass(slots=True)` for type-safe DTOs (RealTradeUpsert, PriceTrendPoint)

## COMMANDS
```bash
# Local dev (no docker)
uv sync
alembic upgrade head
uvicorn src.main:app --reload

# Task management
taskiq worker src.taskiq_app.worker:broker
python -c 'from src.taskiq_app.broker import scheduler; import asyncio; asyncio.run(scheduler.startup())'

# Docker Compose
docker compose up -d  # Starts all 5 services (postgres, redis, api, worker, scheduler)

# Tests
pytest                    # Uses InMemoryBroker (TASKIQ_TESTING=true)
pytest tests/test_tasks.py

# Migrations
alembic revision --autogenerate -m "description"
alembic upgrade head
alembic downgrade -1
```

## NOTES
**Shared infrastructure**: Requires `~/infra` for PostgreSQL/Redis in production
**API key**: PUBLIC_DATA_API_KEY required for MOLIT data (mock data used if missing)
**Port conflicts**: Docker ports 5433 (postgres), 6380 (redis), 8001 (api)
**Testing**: conftest.py auto-initializes InMemoryBroker and dedup cleanup
**Task scheduling**: Cron expression `"0 3 * * *"` = daily 03:00 UTC (12:00 KST)
