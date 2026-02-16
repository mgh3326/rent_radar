"""Web router for dashboard pages."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.region_codes import SIDO_SIGUNGU
from src.db.repositories import (
    fetch_favorites,
    fetch_listings,
)
from src.db.session import get_db_session
from src.services.qa_service import QAService
from src.taskiq_app.tasks import enqueue_crawl_zigbang_listings

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
    _ = session

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
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
    source: str = Form("zigbang"),
    force: bool = Form(False),
) -> RedirectResponse:
    fingerprint = "manual"
    if force:
        fingerprint = f"force-{datetime.now(UTC).isoformat()}"

    if source != "zigbang":
        source = "zigbang"

    result = await enqueue_crawl_zigbang_listings(fingerprint=fingerprint)
    status = "enqueued" if result.get("enqueued") else "duplicate"
    redirect_url = f"/web/listings?source={source}&crawl_status={status}"
    return RedirectResponse(url=redirect_url, status_code=303)


@router.get("/listings", response_class=HTMLResponse)
async def listings(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    region_code: str = "",
    dong: str = "",
    property_type: str = "",
    rent_type: str = "",
    source: str = "zigbang",
    crawl_status: str = "",
) -> HTMLResponse:
    dong_filter = dong if dong else None
    region_code_filter = region_code if region_code else None
    property_type_filter = property_type if property_type else None
    rent_type_filter = rent_type if rent_type else None
    source = "zigbang" if source != "zigbang" else source
    source_filter = source

    listings = await fetch_listings(
        session,
        region_code=region_code_filter,
        dong=dong_filter,
        property_type=property_type_filter,
        rent_type=rent_type_filter,
        source=source_filter,
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


@router.get("/qa", response_class=HTMLResponse)
async def qa_console(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    qa_service = QAService(session)
    summary = await qa_service.get_qa_summary()

    return templates.TemplateResponse(
        "qa.html",
        {
            "request": request,
            "snapshots": summary["snapshots"],
            "issues": summary["issues"],
            "blocker_count": summary["blocker_count"],
            "warning_count": summary["warning_count"],
            "deployment_ready": summary["deployment_ready"],
            "sido_sigungu": SIDO_SIGUNGU,
        },
    )
