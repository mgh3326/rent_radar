"""Repository helpers for real trade queries and persistence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import cast

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.real_trade import RealTrade


@dataclass(slots=True)
class RealTradeUpsert:
    """Payload used to insert official real trade records."""

    property_type: str
    rent_type: str
    region_code: str
    dong: str | None
    apt_name: str | None
    deposit: int
    monthly_rent: int
    area_m2: Decimal | None
    floor: int | None
    contract_year: int
    contract_month: int
    contract_day: int


@dataclass(slots=True)
class PriceTrendPoint:
    """Aggregated monthly trend result."""

    contract_year: int
    contract_month: int
    avg_deposit: float
    avg_monthly_rent: float
    trade_count: int


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
            index_elements=[
                RealTrade.region_code,
                RealTrade.dong,
                RealTrade.apt_name,
                RealTrade.area_m2,
                RealTrade.floor,
                RealTrade.contract_year,
                RealTrade.contract_month,
                RealTrade.contract_day,
                RealTrade.rent_type,
            ]
        ).returning(RealTrade.id)
        result = await session.execute(stmt)
        inserted_ids = result.scalars().all()
        await session.commit()
        return len(inserted_ids)

    inserted = 0
    for row in rows:
        exists_stmt = (
            select(RealTrade.id)
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
    region: str,
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

    if dong:
        stmt = stmt.where(RealTrade.dong.ilike(f"%{dong}%"))
    elif region:
        stmt = stmt.where(RealTrade.dong.ilike(f"%{region}%"))

    result = await session.execute(stmt)
    return list(result.scalars().all())


async def fetch_price_trend(
    session: AsyncSession,
    *,
    region: str,
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

    if dong:
        stmt = stmt.where(RealTrade.dong.ilike(f"%{dong}%"))
    elif region:
        stmt = stmt.where(RealTrade.dong.ilike(f"%{region}%"))

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
