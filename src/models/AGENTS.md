# PROJECT KNOWLEDGE BASE

**Generated:** 2026-02-07
**Branch:** main

## OVERVIEW
SQLAlchemy 2.0 async declarative models for public housing data.

## WHERE TO LOOK
| Task | Location | Notes |
|------|----------|-------|
| Base model | base.py | Common fields: id, created_at, updated_at |
| Listing data | listing.py | Apartment listing records |
| Official trades | real_trade.py | MOLIT public API trade data |

## CONVENTIONS
**Declarative base**: All models inherit from Base with automatic timestamp management
**Column naming**: snake_case for all database columns
**Upsert-ready**: Unique constraints defined on business keys (region_code, apt_name, contract_date)
**Type safety**: Integer/Float types with explicit lengths (e.g., String(255), Numeric(10,2))

## ANTI-PATTERNS (THIS MODULE)
- NEVER use sync SQLAlchemy sessions
- NEVER skip datetime.now() for timestamps (Base handles automatically)
- NEVER add business logic methods to models (keep them data-only)
- NEVER define relationships without lazy='joined' or explicit selectinload
- NEVER use String without length constraint (always use String(N))
