"""Compatibility import for tooling that still references main:app."""

from src.main import app

__all__ = ["app"]
