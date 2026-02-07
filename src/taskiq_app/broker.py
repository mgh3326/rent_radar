"""Taskiq broker and scheduler configuration."""

import importlib

import taskiq_fastapi
from taskiq import InMemoryBroker, TaskiqScheduler
from taskiq.schedule_sources import LabelScheduleSource
from taskiq_redis import RedisAsyncResultBackend, RedisStreamBroker

from src.config import get_settings

settings = get_settings()

if settings.taskiq_testing:
    broker = InMemoryBroker()
else:
    result_backend = RedisAsyncResultBackend(
        redis_url=settings.redis_url,
        result_ex_time=settings.task_result_ttl_seconds,
    )
    broker = RedisStreamBroker(url=settings.redis_url).with_result_backend(
        result_backend
    )

taskiq_fastapi.init(broker, "src.main:app")

scheduler = TaskiqScheduler(
    broker=broker,
    sources=[LabelScheduleSource(broker)],
)


def _register_tasks() -> None:
    importlib.import_module("src.taskiq_app.tasks")


_register_tasks()

__all__ = ["broker", "scheduler"]
