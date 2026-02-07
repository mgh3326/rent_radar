"""Worker entrypoint that guarantees task registration side effects."""

from src.taskiq_app.broker import broker
from src.taskiq_app import tasks as _tasks  # noqa: F401

__all__ = ["broker"]
