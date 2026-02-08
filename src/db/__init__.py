"""Database session and repository utilities."""

from src.db.session import get_db_session, get_engine, get_sessionmaker, session_context
from src.db.repositories import (
    fetch_listings,
    upsert_listings,
    deactivate_stale_listings,
    upsert_sale_trades,
    fetch_sale_trades,
    fetch_price_changes,
    upsert_price_changes,
    upsert_favorites,
    fetch_favorites,
    delete_favorite,
)

__all__ = [
    "get_db_session",
    "get_engine",
    "get_sessionmaker",
    "session_context",
    "fetch_listings",
    "upsert_listings",
    "deactivate_stale_listings",
    "upsert_sale_trades",
    "fetch_sale_trades",
    "fetch_price_changes",
    "upsert_price_changes",
    "upsert_favorites",
    "fetch_favorites",
    "delete_favorite",
]
