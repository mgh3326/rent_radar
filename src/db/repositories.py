"""Repository helpers for real trade queries and persistence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast

from sqlalchemy import delete, func, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.favorite import Favorite
from src.models.listing import Listing
from src.models.price_change import PriceChange
from src.models.real_trade import RealTrade


@dataclass(slots=True)
class RealTradeUpsert:
    """Payload used to insert official real trade records."""

    property_type: str
    rent_type: str
    region_code: str
    dong: str
    apt_name: str
    deposit: int
    monthly_rent: int
    area_m2: Decimal | None
    floor: int
    contract_year: int
    contract_month: int
    contract_day: int
    trade_category: str = "rent"


@dataclass(slots=True)
class PriceTrendPoint:
    """Aggregated monthly trend result."""

    contract_year: int
    contract_month: int
    avg_deposit: float
    avg_monthly_rent: float
    trade_count: int


@dataclass(slots=True)
class ListingUpsert:
    """Payload used to insert/update rental listing records."""

    source: str
    source_id: str
    property_type: str
    rent_type: str
    deposit: int
    monthly_rent: int
    address: str
    dong: str | None
    detail_address: str | None
    area_m2: Decimal | None
    floor: int | None
    total_floors: int | None
    description: str | None
    latitude: Decimal | None
    longitude: Decimal | None


@dataclass(slots=True)
class PriceChangeUpsert:
    """Payload used to insert price change records."""

    listing_id: int
    old_deposit: int
    old_monthly_rent: int
    new_deposit: int
    new_monthly_rent: int
    changed_at: datetime | None = None


@dataclass(slots=True)
class FavoriteUpsert:
    """Payload used to insert user favorite records."""

    user_id: str
    listing_id: int
    deposit_at_save: int | None = None
    monthly_rent_at_save: int | None = None


@dataclass(slots=True)
class RealTradeSummary:
    """Summary statistics for real trade data."""

    total_count: int
    first_contract_year: int | None
    first_contract_month: int | None
    last_contract_year: int | None
    last_contract_month: int | None
    region_counts: list[dict[str, int | str]]


@dataclass(slots=True)
class CrawlSourceSnapshot:
    """Snapshot of crawl source statistics for QA."""

    source: str
    table_name: str
    total_count: int
    last_24h_count: int
    last_updated: datetime | None


@dataclass(slots=True)
class DataQualityIssue:
    """Data quality issue detected by QA rules."""

    id: int
    table_name: str
    issue_type: str
    severity: str  # "blocker" or "warning"
    description: str
    record_data: dict[str, object]


def _subtract_months(year: int, month: int, months: int) -> tuple[int, int]:
    current_year = year
    current_month = month
    for _ in range(max(0, months - 1)):
        current_month -= 1
        if current_month < 1:
            current_month = 12
            current_year -= 1
    return current_year, current_month


def _start_ym(period_months: int) -> int:
    now = datetime.now(UTC)
    year, month = _subtract_months(now.year, now.month, period_months)
    return (year * 100) + month


async def upsert_real_trades(session: AsyncSession, rows: list[RealTradeUpsert]) -> int:
    """Insert official real trade rows and ignore duplicates."""

    if not rows:
        return 0

    from dataclasses import asdict

    values = [asdict(row) for row in rows]
    dialect_name = session.get_bind().dialect.name

    if dialect_name == "postgresql":
        stmt = pg_insert(RealTrade).values(values)
        stmt = stmt.on_conflict_do_nothing(
            constraint="uq_real_trades_identity"
        ).returning(RealTrade.id)
        result = await session.execute(stmt)
        inserted_ids = result.scalars().all()
        await session.commit()
        return len(inserted_ids)

    inserted = 0
    for row in rows:
        exists_stmt = (
            select(RealTrade.id)
            .where(RealTrade.property_type == row.property_type)
            .where(RealTrade.region_code == row.region_code)
            .where(RealTrade.dong == row.dong)
            .where(RealTrade.apt_name == row.apt_name)
            .where(RealTrade.area_m2 == row.area_m2)
            .where(RealTrade.floor == row.floor)
            .where(RealTrade.contract_year == row.contract_year)
            .where(RealTrade.contract_month == row.contract_month)
            .where(RealTrade.contract_day == row.contract_day)
            .where(RealTrade.rent_type == row.rent_type)
        )
        if (await session.execute(exists_stmt)).scalar_one_or_none() is not None:
            continue
        session.add(RealTrade(**row.__dict__))
        inserted += 1

    await session.commit()
    return inserted


async def fetch_real_prices(
    session: AsyncSession,
    *,
    region_code: str | None,
    dong: str | None,
    property_type: str,
    period_months: int,
    limit: int = 200,
) -> list[RealTrade]:
    """Fetch real trade records for MCP tool responses."""

    ym_expr = (RealTrade.contract_year * 100) + RealTrade.contract_month
    stmt = (
        select(RealTrade)
        .where(RealTrade.property_type == property_type)
        .where(ym_expr >= _start_ym(period_months))
        .order_by(
            RealTrade.contract_year.desc(),
            RealTrade.contract_month.desc(),
            RealTrade.contract_day.desc(),
        )
        .limit(limit)
    )

    if region_code:
        stmt = stmt.where(RealTrade.region_code == region_code)
    if dong:
        stmt = stmt.where(RealTrade.dong.ilike(f"%{dong}%"))

    result = await session.execute(stmt)
    return list(result.scalars().all())


@dataclass(slots=True)
class MarketStats:
    """Market statistics for a listing."""

    avg_deposit: float
    sample_count: int


async def fetch_market_stats(
    session: AsyncSession,
    *,
    property_type: str,
    dong: str | None,
    area_m2: Decimal | None,
    period_months: int = 12,
) -> MarketStats | None:
    """Fetch market average deposit for comparable properties."""

    ym_expr = (RealTrade.contract_year * 100) + RealTrade.contract_month
    stmt = (
        select(
            func.avg(RealTrade.deposit),
            func.count(RealTrade.id),
        )
        .where(RealTrade.property_type == property_type)
        .where(ym_expr >= _start_ym(period_months))
    )

    if dong:
        stmt = stmt.where(RealTrade.dong.ilike(f"%{dong}%"))

    if area_m2 is not None:
        stmt = stmt.where(
            RealTrade.area_m2 >= area_m2 - Decimal("5"),
            RealTrade.area_m2 <= area_m2 + Decimal("5"),
        )

    row = (await session.execute(stmt)).first()
    if row is None or row[1] == 0:
        return None

    return MarketStats(
        avg_deposit=float(row[0] or 0),
        sample_count=int(row[1]),
    )


async def fetch_price_trend(
    session: AsyncSession,
    *,
    region_code: str | None,
    dong: str | None,
    property_type: str,
    period_months: int,
) -> list[PriceTrendPoint]:
    """Fetch monthly average trend points for deposits and rents."""

    ym_expr = (RealTrade.contract_year * 100) + RealTrade.contract_month
    stmt = (
        select(
            RealTrade.contract_year,
            RealTrade.contract_month,
            func.avg(RealTrade.deposit),
            func.avg(RealTrade.monthly_rent),
            func.count(RealTrade.id),
        )
        .where(RealTrade.property_type == property_type)
        .where(ym_expr >= _start_ym(period_months))
        .group_by(RealTrade.contract_year, RealTrade.contract_month)
        .order_by(RealTrade.contract_year.asc(), RealTrade.contract_month.asc())
    )

    if region_code:
        stmt = stmt.where(RealTrade.region_code == region_code)
    if dong:
        stmt = stmt.where(RealTrade.dong.ilike(f"%{dong}%"))

    rows = (await session.execute(stmt)).all()
    trend_points: list[PriceTrendPoint] = []
    for row in rows:
        year = cast(int, row[0])
        month = cast(int, row[1])
        avg_deposit = cast(float | None, row[2])
        avg_monthly_rent = cast(float | None, row[3])
        count = cast(int | None, row[4])
        trend_points.append(
            PriceTrendPoint(
                contract_year=int(year),
                contract_month=int(month),
                avg_deposit=float(avg_deposit or 0),
                avg_monthly_rent=float(avg_monthly_rent or 0),
                trade_count=int(count or 0),
            )
        )
    return trend_points


async def fetch_real_trade_summary(session: AsyncSession) -> RealTradeSummary:
    """Fetch summary statistics for all real trade data."""

    total_stmt = select(func.count(RealTrade.id))
    total_count = (await session.execute(total_stmt)).scalar_one_or_none() or 0

    first_stmt = (
        select(RealTrade.contract_year, RealTrade.contract_month)
        .order_by(RealTrade.contract_year.asc(), RealTrade.contract_month.asc())
        .limit(1)
    )
    first_row = (await session.execute(first_stmt)).first()
    first_year = cast(int | None, first_row[0]) if first_row else None
    first_month = cast(int | None, first_row[1]) if first_row else None

    last_stmt = (
        select(RealTrade.contract_year, RealTrade.contract_month)
        .order_by(RealTrade.contract_year.desc(), RealTrade.contract_month.desc())
        .limit(1)
    )
    last_row = (await session.execute(last_stmt)).first()
    last_year = cast(int | None, last_row[0]) if last_row else None
    last_month = cast(int | None, last_row[1]) if last_row else None

    region_stmt = (
        select(
            RealTrade.region_code,
            RealTrade.dong,
            func.count(RealTrade.id).label("count"),
        )
        .group_by(RealTrade.region_code, RealTrade.dong)
        .order_by(RealTrade.region_code.asc(), RealTrade.dong.asc())
    )
    region_rows = (await session.execute(region_stmt)).all()
    region_counts = [
        {"region_code": row[0], "dong": row[1], "count": int(row[2])}
        for row in region_rows
    ]

    return RealTradeSummary(
        total_count=total_count,
        first_contract_year=first_year,
        first_contract_month=first_month,
        last_contract_year=last_year,
        last_contract_month=last_month,
        region_counts=region_counts,
    )


async def upsert_sale_trades(session: AsyncSession, rows: list[RealTradeUpsert]) -> int:
    """Insert sale trade records with ON CONFLICT DO NOTHING."""

    if not rows:
        return 0

    from dataclasses import asdict

    values = [asdict(row) for row in rows]
    dialect_name = session.get_bind().dialect.name

    if dialect_name == "postgresql":
        stmt = pg_insert(RealTrade).values(values)
        stmt = stmt.on_conflict_do_nothing(
            constraint="uq_real_trades_identity"
        ).returning(RealTrade.id)
        result = await session.execute(stmt)
        inserted_ids = result.scalars().all()
        await session.commit()
        return len(inserted_ids)

    inserted = 0
    for row in rows:
        exists_stmt = (
            select(RealTrade.id)
            .where(RealTrade.property_type == row.property_type)
            .where(RealTrade.region_code == row.region_code)
            .where(RealTrade.dong == row.dong)
            .where(RealTrade.apt_name == row.apt_name)
            .where(RealTrade.area_m2 == row.area_m2)
            .where(RealTrade.floor == row.floor)
            .where(RealTrade.contract_year == row.contract_year)
            .where(RealTrade.contract_month == row.contract_month)
            .where(RealTrade.contract_day == row.contract_day)
            .where(RealTrade.rent_type == row.rent_type)
        )
        if (await session.execute(exists_stmt)).scalar_one_or_none() is not None:
            continue
        session.add(RealTrade(**row.__dict__))
        inserted += 1

    await session.commit()
    return inserted


async def fetch_sale_trades(
    session: AsyncSession,
    *,
    region_code: str | None,
    dong: str | None,
    property_type: str,
    start_year_month: str | None,
    end_year_month: str | None,
    trade_category: str = "sale",
) -> list[RealTrade]:
    """Fetch sale trade records by filters."""

    ym_expr = (RealTrade.contract_year * 100) + RealTrade.contract_month
    stmt = (
        select(RealTrade)
        .where(RealTrade.trade_category == trade_category)
        .order_by(
            RealTrade.contract_year.desc(),
            RealTrade.contract_month.desc(),
            RealTrade.contract_day.desc(),
        )
        .limit(200)
    )

    if region_code:
        stmt = stmt.where(RealTrade.region_code == region_code)

    if dong:
        stmt = stmt.where(RealTrade.dong.ilike(f"%{dong}%"))

    if property_type:
        stmt = stmt.where(RealTrade.property_type == property_type)

    if start_year_month:
        ym = int(start_year_month[:6])
        stmt = stmt.where(
            RealTrade.contract_year * 100 + RealTrade.contract_month >= ym
        )
        if end_year_month:
            end_ym = int(end_year_month[:6])
            stmt = stmt.where(
                RealTrade.contract_year * 100 + RealTrade.contract_month < end_ym
            )

    result = await session.execute(stmt)
    return list(result.scalars().all())


async def upsert_listings(session: AsyncSession, rows: list[ListingUpsert]) -> int:
    """Insert or update rental listing rows with ON CONFLICT DO UPDATE."""

    if not rows:
        return 0

    from dataclasses import asdict

    seen: dict[tuple[str, str], ListingUpsert] = {}
    for row in rows:
        seen[(row.source, row.source_id)] = row
    rows = list(seen.values())

    values = [asdict(row) for row in rows]
    dialect_name = session.get_bind().dialect.name
    now = datetime.now(UTC)

    if dialect_name == "postgresql":
        sources = [(row.source, row.source_id) for row in rows]
        fetch_stmt = select(
            Listing.id,
            Listing.source,
            Listing.source_id,
            Listing.deposit,
            Listing.monthly_rent,
        ).where(tuple_(Listing.source, Listing.source_id).in_(sources))
        existing_map = {
            (r.source, r.source_id): (r.id, r.deposit, r.monthly_rent)
            for r in (await session.execute(fetch_stmt)).all()
        }

        stmt = pg_insert(Listing).values(values)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_listings_source_source_id",
            set_={
                "deposit": stmt.excluded.deposit,
                "monthly_rent": stmt.excluded.monthly_rent,
                "address": stmt.excluded.address,
                "dong": stmt.excluded.dong,
                "detail_address": stmt.excluded.detail_address,
                "area_m2": stmt.excluded.area_m2,
                "floor": stmt.excluded.floor,
                "total_floors": stmt.excluded.total_floors,
                "description": stmt.excluded.description,
                "latitude": stmt.excluded.latitude,
                "longitude": stmt.excluded.longitude,
                "last_seen_at": now,
                "is_active": True,
            },
        ).returning(Listing.id)
        result = await session.execute(stmt)
        affected_ids = result.scalars().all()

        price_changes: list[PriceChangeUpsert] = []
        for row in rows:
            key = (row.source, row.source_id)
            if key in existing_map:
                listing_id, old_deposit, old_monthly_rent = existing_map[key]
                if old_deposit != row.deposit or old_monthly_rent != row.monthly_rent:
                    price_changes.append(
                        PriceChangeUpsert(
                            listing_id=listing_id,
                            old_deposit=old_deposit,
                            old_monthly_rent=old_monthly_rent,
                            new_deposit=row.deposit,
                            new_monthly_rent=row.monthly_rent,
                            changed_at=now,
                        )
                    )

        if price_changes:
            await upsert_price_changes(session, price_changes)

        await session.commit()
        return len(affected_ids)

    inserted = 0
    for row in rows:
        exists_stmt = (
            select(Listing.id, Listing.deposit, Listing.monthly_rent)
            .where(Listing.source == row.source)
            .where(Listing.source_id == row.source_id)
        )
        existing = (await session.execute(exists_stmt)).first()

        if existing is None:
            new_listing = Listing(
                source=row.source,
                source_id=row.source_id,
                property_type=row.property_type,
                rent_type=row.rent_type,
                deposit=row.deposit,
                monthly_rent=row.monthly_rent,
                address=row.address,
                dong=row.dong,
                detail_address=row.detail_address,
                area_m2=row.area_m2,
                floor=row.floor,
                total_floors=row.total_floors,
                description=row.description,
                latitude=row.latitude,
                longitude=row.longitude,
                is_active=True,
                first_seen_at=now,
                last_seen_at=now,
            )
            session.add(new_listing)
            inserted += 1
        else:
            listing_id, old_deposit, old_monthly_rent = existing
            if old_deposit != row.deposit or old_monthly_rent != row.monthly_rent:
                price_change = PriceChangeUpsert(
                    listing_id=listing_id,
                    old_deposit=old_deposit,
                    old_monthly_rent=old_monthly_rent,
                    new_deposit=row.deposit,
                    new_monthly_rent=row.monthly_rent,
                    changed_at=now,
                )
                await upsert_price_changes(session, [price_change])

            stmt = (
                update(Listing)
                .where(Listing.id == listing_id)
                .values(
                    deposit=row.deposit,
                    monthly_rent=row.monthly_rent,
                    address=row.address,
                    dong=row.dong,
                    detail_address=row.detail_address,
                    area_m2=row.area_m2,
                    floor=row.floor,
                    total_floors=row.total_floors,
                    description=row.description,
                    latitude=row.latitude,
                    longitude=row.longitude,
                    last_seen_at=now,
                    is_active=True,
                )
            )
            await session.execute(stmt)
            inserted += 1

    await session.commit()
    return inserted


async def fetch_listings(
    session: AsyncSession,
    *,
    region_code: str | None = None,
    dong: str | None = None,
    property_type: str | None = None,
    rent_type: str | None = None,
    source: str | None = None,
    min_deposit: int | None = None,
    max_deposit: int | None = None,
    min_monthly_rent: int | None = None,
    max_monthly_rent: int | None = None,
    min_area: Decimal | None = None,
    max_area: Decimal | None = None,
    min_floor: int | None = None,
    max_floor: int | None = None,
    is_active: bool | None = True,
    limit: int = 200,
) -> list[Listing]:
    stmt = select(Listing).order_by(Listing.last_seen_at.desc())

    if is_active is not None:
        stmt = stmt.where(Listing.is_active == is_active)

    if region_code:
        stmt = stmt.where(Listing.address.ilike(f"%{region_code}%"))

    if dong:
        stmt = stmt.where(Listing.dong.ilike(f"%{dong}%"))

    if property_type:
        stmt = stmt.where(Listing.property_type == property_type)

    if rent_type:
        stmt = stmt.where(Listing.rent_type == rent_type)

    if source:
        stmt = stmt.where(Listing.source == source)

    if min_deposit is not None:
        stmt = stmt.where(Listing.deposit >= min_deposit)

    if max_deposit is not None:
        stmt = stmt.where(Listing.deposit <= max_deposit)

    if min_monthly_rent is not None:
        stmt = stmt.where(Listing.monthly_rent >= min_monthly_rent)

    if max_monthly_rent is not None:
        stmt = stmt.where(Listing.monthly_rent <= max_monthly_rent)

    if min_area is not None:
        stmt = stmt.where(Listing.area_m2 >= min_area)

    if max_area is not None:
        stmt = stmt.where(Listing.area_m2 <= max_area)

    if min_floor is not None:
        stmt = stmt.where(Listing.floor >= min_floor)

    if max_floor is not None:
        stmt = stmt.where(Listing.floor <= max_floor)

    stmt = stmt.limit(limit)

    result = await session.execute(stmt)
    return list(result.scalars().all())


async def fetch_listings_by_ids(
    session: AsyncSession,
    listing_ids: list[int],
    *,
    is_active: bool | None = True,
) -> list[Listing]:
    """Fetch listings by exact IDs with optional active filter.

    Preserves input order in the returned list.
    """
    if not listing_ids:
        return []

    stmt = select(Listing).where(Listing.id.in_(listing_ids))

    if is_active is not None:
        stmt = stmt.where(Listing.is_active == is_active)

    result = await session.execute(stmt)
    listings = {lst.id: lst for lst in result.scalars().all()}

    return [listings[lid] for lid in listing_ids if lid in listings]


async def deactivate_stale_listings(
    session: AsyncSession, source: str, threshold_hours: int = 48
) -> int:
    """Deactivate listings that haven't been seen recently."""

    threshold_time = datetime.now(UTC) - timedelta(hours=threshold_hours)

    stmt = (
        update(Listing)
        .where(Listing.source == source)
        .where(Listing.is_active == True)
        .where(Listing.last_seen_at < threshold_time)
        .values(is_active=False)
        .returning(Listing.id)
    )

    result = await session.execute(stmt)
    await session.commit()
    return len(result.scalars().all())


async def upsert_price_changes(
    session: AsyncSession, rows: list[PriceChangeUpsert]
) -> int:
    """Insert price change records."""

    if not rows:
        return 0

    from dataclasses import asdict

    values = [asdict(row) for row in rows]
    dialect_name = session.get_bind().dialect.name

    if dialect_name == "postgresql":
        stmt = pg_insert(PriceChange).values(values)
        stmt = stmt.on_conflict_do_nothing().returning(PriceChange.id)
        result = await session.execute(stmt)
        inserted_ids = result.scalars().all()
        await session.commit()
        return len(inserted_ids)

    inserted = 0
    for row in rows:
        session.add(PriceChange(**row.__dict__))
        inserted += 1

    await session.commit()
    return inserted


async def fetch_price_changes(
    session: AsyncSession,
    *,
    listing_id: int | None = None,
    dong: str | None = None,
    property_type: str | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    limit: int = 200,
) -> list[PriceChange]:
    """Fetch price change records with optional filters."""

    stmt = select(PriceChange).order_by(PriceChange.changed_at.desc())

    if listing_id:
        stmt = stmt.where(PriceChange.listing_id == listing_id)
    else:
        stmt = stmt.join(Listing, PriceChange.listing_id == Listing.id)

        if dong:
            stmt = stmt.where(Listing.dong == dong)

        if property_type:
            stmt = stmt.where(Listing.property_type == property_type)

    if start_date:
        stmt = stmt.where(PriceChange.changed_at >= start_date)

    if end_date:
        stmt = stmt.where(PriceChange.changed_at <= end_date)

    stmt = stmt.limit(limit)

    result = await session.execute(stmt)
    return list(result.scalars().all())


async def upsert_favorites(session: AsyncSession, rows: list[FavoriteUpsert]) -> int:
    """Insert favorite records with ON CONFLICT DO NOTHING."""

    if not rows:
        return 0

    from dataclasses import asdict

    values = [asdict(row) for row in rows]
    dialect_name = session.get_bind().dialect.name

    if dialect_name == "postgresql":
        stmt = pg_insert(Favorite).values(values)
        stmt = stmt.on_conflict_do_nothing().returning(Favorite.id)
        result = await session.execute(stmt)
        inserted_ids = result.scalars().all()
        await session.commit()
        return len(inserted_ids)

    inserted = 0
    for row in rows:
        exists_stmt = (
            select(Favorite.id)
            .where(Favorite.user_id == row.user_id)
            .where(Favorite.listing_id == row.listing_id)
        )
        if (await session.execute(exists_stmt)).scalar_one_or_none() is not None:
            continue
        session.add(Favorite(**row.__dict__))
        inserted += 1

    await session.commit()
    return inserted


async def fetch_favorites(
    session: AsyncSession,
    *,
    user_id: str | None = None,
    listing_id: int | None = None,
    limit: int = 200,
) -> list[Favorite]:
    """Fetch favorite records with optional filters."""

    stmt = select(Favorite).order_by(Favorite.created_at.desc())

    if user_id:
        stmt = stmt.where(Favorite.user_id == user_id)

    if listing_id:
        stmt = stmt.where(Favorite.listing_id == listing_id)

    stmt = stmt.limit(limit)

    result = await session.execute(stmt)
    return list(result.scalars().all())


async def delete_favorite(session: AsyncSession, user_id: str, listing_id: int) -> bool:
    """Delete a favorite record."""

    stmt = (
        select(Favorite.id)
        .where(Favorite.user_id == user_id)
        .where(Favorite.listing_id == listing_id)
    )
    result = (await session.execute(stmt)).first()

    if result is None:
        return False

    delete_stmt = (
        delete(Favorite)
        .where(Favorite.user_id == user_id)
        .where(Favorite.listing_id == listing_id)
    )
    await session.execute(delete_stmt)
    await session.commit()
    return True


async def fetch_crawl_snapshots(
    session: AsyncSession, lookback_hours: int = 24
) -> list[CrawlSourceSnapshot]:
    """Fetch crawl source statistics for QA monitoring."""
    threshold = datetime.now(UTC) - timedelta(hours=lookback_hours)

    real_trade_total = (
        await session.execute(select(func.count(RealTrade.id)))
    ).scalar_one_or_none() or 0
    real_trade_recent = (
        await session.execute(
            select(func.count(RealTrade.id)).where(RealTrade.created_at >= threshold)
        )
    ).scalar_one_or_none() or 0
    real_trade_last = (
        await session.execute(
            select(RealTrade.created_at).order_by(RealTrade.created_at.desc()).limit(1)
        )
    ).scalar_one_or_none()

    listing_total = (
        await session.execute(select(func.count(Listing.id)))
    ).scalar_one_or_none() or 0
    listing_recent = (
        await session.execute(
            select(func.count(Listing.id)).where(Listing.last_seen_at >= threshold)
        )
    ).scalar_one_or_none() or 0
    listing_last = (
        await session.execute(
            select(Listing.last_seen_at).order_by(Listing.last_seen_at.desc()).limit(1)
        )
    ).scalar_one_or_none()

    return [
        CrawlSourceSnapshot(
            source="public_api",
            table_name="real_trades",
            total_count=real_trade_total,
            last_24h_count=real_trade_recent,
            last_updated=real_trade_last,
        ),
        CrawlSourceSnapshot(
            source="naver/zigbang",
            table_name="listings",
            total_count=listing_total,
            last_24h_count=listing_recent,
            last_updated=listing_last,
        ),
    ]


async def fetch_data_quality_issues(
    session: AsyncSession, limit: int = 100
) -> list[DataQualityIssue]:
    """Fetch data quality issues based on predefined rules."""
    issues: list[DataQualityIssue] = []
    now = datetime.now(UTC)
    stale_threshold = now - timedelta(days=7)
    future_contract_clause = (
        (RealTrade.contract_year > now.year)
        | (
            (RealTrade.contract_year == now.year)
            & (RealTrade.contract_month > now.month)
        )
        | (
            (RealTrade.contract_year == now.year)
            & (RealTrade.contract_month == now.month)
            & (RealTrade.contract_day > now.day)
        )
    )

    blockers = (
        (
            await session.execute(
                select(RealTrade)
                .where(
                    (RealTrade.deposit <= 0)
                    | (RealTrade.monthly_rent < 0)
                    | ((RealTrade.rent_type == "jeonse") & (RealTrade.monthly_rent > 0))
                    | (
                        (RealTrade.rent_type == "monthly")
                        & (RealTrade.monthly_rent == 0)
                    )
                    | future_contract_clause
                )
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )

    for rt in blockers:
        issue_type = []
        if rt.deposit <= 0:
            issue_type.append("deposit<=0")
        if rt.monthly_rent < 0:
            issue_type.append("monthly_rent<0")
        if rt.rent_type == "jeonse" and rt.monthly_rent > 0:
            issue_type.append("jeonse_with_monthly_rent")
        if rt.rent_type == "monthly" and rt.monthly_rent == 0:
            issue_type.append("monthly_with_zero_rent")
        if (
            rt.contract_year > now.year
            or (rt.contract_year == now.year and rt.contract_month > now.month)
            or (
                rt.contract_year == now.year
                and rt.contract_month == now.month
                and rt.contract_day > now.day
            )
        ):
            issue_type.append("future_contract_date")

        issues.append(
            DataQualityIssue(
                id=rt.id,
                table_name="real_trades",
                issue_type=",".join(issue_type),
                severity="blocker",
                description=f"RealTrade #{rt.id}: {'; '.join(issue_type)}",
                record_data={
                    "deposit": rt.deposit,
                    "monthly_rent": rt.monthly_rent,
                    "rent_type": rt.rent_type,
                    "dong": rt.dong,
                    "apt_name": rt.apt_name,
                    "contract_year": rt.contract_year,
                    "contract_month": rt.contract_month,
                    "contract_day": rt.contract_day,
                },
            )
        )

    warnings = (
        (
            await session.execute(
                select(RealTrade)
                .where(
                    ((RealTrade.area_m2 <= 10) | (RealTrade.area_m2 > 400))
                    | ((RealTrade.floor < -3) | (RealTrade.floor > 100))
                )
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )

    for rt in warnings:
        issue_type = []
        if rt.area_m2 is not None and (rt.area_m2 <= 10 or rt.area_m2 > 400):
            issue_type.append(f"area_m2={rt.area_m2}")
        if rt.floor < -3 or rt.floor > 100:
            issue_type.append(f"floor={rt.floor}")

        issues.append(
            DataQualityIssue(
                id=rt.id,
                table_name="real_trades",
                issue_type=",".join(issue_type),
                severity="warning",
                description=f"RealTrade #{rt.id}: {'; '.join(issue_type)}",
                record_data={
                    "area_m2": float(rt.area_m2) if rt.area_m2 else None,
                    "floor": rt.floor,
                    "dong": rt.dong,
                    "apt_name": rt.apt_name,
                },
            )
        )

    listing_issues = (
        (
            await session.execute(
                select(Listing)
                .where(
                    (Listing.deposit <= 0)
                    | (Listing.monthly_rent < 0)
                    | (
                        (Listing.is_active == True)
                        & (Listing.last_seen_at < stale_threshold)
                    )
                )
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )

    for lst in listing_issues:
        issue_type = []
        severity = "warning"

        if lst.deposit <= 0:
            issue_type.append("deposit<=0")
            severity = "blocker"
        if lst.monthly_rent < 0:
            issue_type.append("monthly_rent<0")
            severity = "blocker"
        if lst.is_active and lst.last_seen_at and lst.last_seen_at < stale_threshold:
            issue_type.append("stale_active_listing")

        issues.append(
            DataQualityIssue(
                id=lst.id,
                table_name="listings",
                issue_type=",".join(issue_type),
                severity=severity,
                description=f"Listing #{lst.id}: {'; '.join(issue_type)}",
                record_data={
                    "deposit": lst.deposit,
                    "monthly_rent": lst.monthly_rent,
                    "is_active": lst.is_active,
                    "last_seen_at": lst.last_seen_at.isoformat()
                    if lst.last_seen_at
                    else None,
                    "source": lst.source,
                },
            )
        )

    blockers_first = sorted(
        issues, key=lambda x: (0 if x.severity == "blocker" else 1, x.table_name)
    )
    return blockers_first[:limit]
