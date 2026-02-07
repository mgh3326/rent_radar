# DATABASE REPOSITORY LAYER

## OVERVIEW
Async database access layer providing session management and repository patterns for PostgreSQL operations.

## WHERE TO LOOK
| Component | Location | Purpose |
|-----------|----------|---------|
| Session manager | session.py:session_context() | Async context manager for DB sessions |
| Real trade upsert | repositories.py:upsert_real_trades() | PostgreSQL ON CONFLICT for duplicate-safe inserts |
| Price queries | repositories.py:fetch_real_prices() | Filtered queries by region/dong/property_type |
| Trend aggregation | repositories.py:fetch_price_trend() | Monthly averages via func.avg() and group_by |
| DTOs | repositories.py:dataclasses | RealTradeUpsert, PriceTrendPoint (slots=True)

## CONVENTIONS
- **Always use session_context()**: All DB operations must run within this async context manager
- **Dataclass DTOs**: Repository methods use @dataclass(slots=True) for type-safe data transfer
- **PostgreSQL upserts**: ON CONFLICT DO NOTHING with 9-field index_elements for duplicate detection
- **Dialect safety**: Fallback EXISTS check for non-PostgreSQL databases

## ANTI-PATTERNS (THIS MODULE)
- NEVER use sync sessions or sessionmaker
- NEVER commit transactions manually (context manager handles it)
- NEVER use raw SQL strings (SQLAlchemy Core for dialect compatibility)
- NEVER skip session_context() wrapper in repository methods
- NEVER use dataclasses without slots=True for DTOs
