"""Test fixtures for Taskiq and async runtime."""

import os
import sys
from collections.abc import AsyncIterator
from pathlib import Path

os.environ["TASKIQ_TESTING"] = "1"

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import pytest

from src.taskiq_app.broker import broker
from src.taskiq_app.dedup import _MEMORY_LOCKS


@pytest.fixture(scope="function", autouse=True)
async def init_taskiq() -> AsyncIterator[None]:
    """Initialize broker per test when using InMemoryBroker."""

    _MEMORY_LOCKS.clear()
    await broker.startup()
    yield
    await broker.shutdown()
    _MEMORY_LOCKS.clear()


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
