"""Web router for dashboard pages."""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.region_codes import SIDO_SIGUNGU
from src.db.repositories import (
    fetch_favorites,
    fetch_listings,
    fetch_price_changes,
    fetch_real_trade_summary,
)
from src.db.session import get_db_session
from src.services import PriceService
from src.taskiq_app.tasks import (
    enqueue_crawl_real_trade,
    enqueue_crawl_naver_listings,
    enqueue_crawl_zigbang_listings,
)

templates = Jinja2Templates(directory="src/web/templates")

router = APIRouter(prefix="/web", tags=["web"])


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    region_code: str = "",
    dong: str = "",
    property_type: str = "apt",
    crawl_status: str = "",
) -> HTMLResponse:
    """Render dashboard with summary, list, and trend tables."""

    summary = await fetch_real_trade_summary(session)

    price_service = PriceService(session)

    dong_filter = dong if dong else None
    region_code_filter = region_code if region_code else None
    property_type_filter = property_type if property_type else "apt"

    real_prices = await price_service.get_real_price(
        region_code=region_code_filter,
        dong=dong_filter,
        property_type=property_type_filter,
        period_months=24,
    )
    price_trend = await price_service.get_price_trend(
        region_code=region_code_filter,
        dong=dong_filter,
        property_type=property_type_filter,
        period_months=24,
    )

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "summary": summary,
            "real_prices": real_prices,
            "price_trend": price_trend,
            "filters": {
                "region_code": region_code,
                "dong": dong,
                "property_type": property_type,
            },
            "crawl_status": crawl_status,
            "sido_sigungu": SIDO_SIGUNGU,
        },
    )


@router.post("/crawl-listings", response_class=RedirectResponse)
async def trigger_crawl_listings(
    source: str = Form("all"),
) -> RedirectResponse:
    """Trigger crawl for listings (naver/zigbang/all)."""

    results = []
    if source in ("naver", "all"):
        results.append(await enqueue_crawl_naver_listings())
    if source in ("zigbang", "all"):
        results.append(await enqueue_crawl_zigbang_listings())

    any_enqueued = any(r.get("enqueued") for r in results)
    status = "enqueued" if any_enqueued else "duplicate"
    redirect_url = f"/web/listings?source={source}&crawl_status={status}"
    return RedirectResponse(url=redirect_url, status_code=303)


@router.post("/crawl")
async def trigger_crawl(
    region_code: str = Form(...),
    property_type: str = Form("apt"),
    start_year_month: str = Form(""),
    end_year_month: str = Form(""),
) -> RedirectResponse:
    """Trigger manual crawl task and redirect to dashboard with status."""

    result = await enqueue_crawl_real_trade(fingerprint="manual")
    status = "enqueued" if result.get("enqueued") else "duplicate"
    redirect_url = f"/web/?region_code={region_code}&property_type={property_type}&crawl_status={status}"
    return RedirectResponse(url=redirect_url, status_code=303)


@router.get("/listings", response_class=HTMLResponse)
async def listings(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    region_code: str = "",
    dong: str = "",
    property_type: str = "",
    rent_type: str = "",
    source: str = "naver",
    crawl_status: str = "",
) -> HTMLResponse:
    """Render rental listings with filters."""

    dong_filter = dong if dong else None
    region_code_filter = region_code if region_code else None
    property_type_filter = property_type if property_type else None
    rent_type_filter = rent_type if rent_type else None

    listings = await fetch_listings(
        session,
        region_code=region_code_filter,
        dong=dong_filter,
        property_type=property_type_filter,
        rent_type=rent_type_filter,
        is_active=True,
        limit=100,
    )

    return templates.TemplateResponse(
        "listings.html",
        {
            "request": request,
            "listings": listings,
            "filters": {
                "region_code": region_code,
                "dong": dong,
                "property_type": property_type,
                "rent_type": rent_type,
                "source": source,
            },
            "crawl_status": crawl_status,
            "sido_sigungu": SIDO_SIGUNGU,
        },
    )


@router.get("/favorites", response_class=HTMLResponse)
async def favorites(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    """Render favorite listings for comparison."""

    favorites = await fetch_favorites(session, limit=50)

    return templates.TemplateResponse(
        "favorites.html",
        {
            "request": request,
            "favorites": favorites,
        },
    )


@router.post("/favorites/{id}", response_class=RedirectResponse)
async def toggle_favorite(
    id: int,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> RedirectResponse:
    """Toggle listing favorite status."""

    existing = await fetch_favorites(session, user_id="default", listing_id=id)
    if existing:
        from src.db.repositories import delete_favorite

        await delete_favorite(session, user_id="default", listing_id=id)
    else:
        from src.db.repositories import upsert_favorites, FavoriteUpsert

        await upsert_favorites(
            session, [FavoriteUpsert(user_id="default", listing_id=id)]
        )

    referer = request.headers.get("referer", "/web/favorites")
    return RedirectResponse(url=referer, status_code=303)


@router.get("/price-changes", response_class=HTMLResponse)
async def price_changes(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    dong: str = "",
    property_type: str = "",
    days: int = 30,
) -> HTMLResponse:
    """Render price change charts."""

    price_service = PriceService(session)
    dong_filter = dong if dong else None
    property_type_filter = property_type if property_type else None

    price_changes = await fetch_price_changes(
        session,
        dong=dong_filter,
        property_type=property_type_filter,
        limit=days,
    )

    return templates.TemplateResponse(
        "price_changes.html",
        {
            "request": request,
            "price_changes": price_changes,
            "filters": {
                "dong": dong,
                "property_type": property_type,
                "days": days,
            },
            "sido_sigungu": SIDO_SIGUNGU,
        },
    )
