"""Base crawler definitions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass(slots=True)
class CrawlResult(Generic[T]):
    """Generic crawler result payload."""

    count: int
    rows: list[T]
