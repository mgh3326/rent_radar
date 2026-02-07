## OVERVIEW
Async task queue with TaskIQ: broker config, worker entrypoint, scheduled crawling tasks, and Redis deduplication.

## WHERE TO LOOK
| Task | Location | Notes |
|------|----------|-------|
| Broker setup | broker.py | InMemoryBroker (tests) vs RedisStreamBroker (prod) |
| Worker entry | worker.py | `broker.is_worker_process` detection flag |
| Task definitions | tasks.py | `crawl_real_trade` (cron: 0 3 * * *), enqueue wrapper |
| Deduplication | dedup.py | `acquire_dedup_lock`, `build_dedup_key` with Redis NX |
| Scheduler startup | broker.py | scheduler lifecycle via FastAPI lifespan |

## CONVENTIONS
**Two-phase dedup**: Enqueue lock (task enqueue time) + execution lock (task run time) prevents race conditions
**Broker detection**: `broker.is_worker_process` prevents double-initialization in non-worker processes
**Testing mode**: `TASKIQ_TESTING=true` switches to InMemoryBroker (no Redis required)
**Environment-driven**: `os.getenv("TASKIQ_TESTING")` determines broker type at import time

## ANTI-PATTERNS
- NEVER initialize broker multiple times (check `broker.is_worker_process` in lifespan)
- NEVER run scheduled tasks without `await scheduler.startup()` first
- NEVER use synchronous Redis operations for dedup locks (always async)
- NEVER skip the enqueue lock phase - execution lock alone is insufficient for race prevention
