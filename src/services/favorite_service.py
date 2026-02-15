"""Business logic for user favorite management."""

from sqlalchemy.ext.asyncio import AsyncSession

from src.db.repositories import (
    FavoriteUpsert,
    delete_favorite,
    fetch_favorites,
    fetch_listings_by_ids,
    upsert_favorites,
)


class FavoriteService:
    """Service layer for MCP favorite tools."""

    _session: AsyncSession

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_favorite(self, user_id: str, listing_id: int) -> dict[str, object]:
        """Add a listing to user favorites with price snapshot."""

        listings = await fetch_listings_by_ids(
            self._session, [listing_id], is_active=True
        )
        listing = listings[0] if listings else None

        if not listing:
            return {
                "user_id": user_id,
                "listing_id": listing_id,
                "status": "not_found",
                "message": "Listing not found or inactive",
            }

        inserted = await upsert_favorites(
            self._session,
            [
                FavoriteUpsert(
                    user_id=user_id,
                    listing_id=listing_id,
                    deposit_at_save=listing.deposit,
                    monthly_rent_at_save=listing.monthly_rent,
                )
            ],
        )

        if inserted == 0:
            return {
                "user_id": user_id,
                "listing_id": listing_id,
                "status": "already_exists",
                "message": "Listing already in favorites",
            }

        return {
            "user_id": user_id,
            "listing_id": listing_id,
            "status": "added",
            "message": "Listing added to favorites",
        }

    async def list_favorites(
        self, user_id: str, limit: int = 50
    ) -> list[dict[str, object]]:
        """List all favorites for a user with listing details."""

        favorites = await fetch_favorites(self._session, user_id=user_id, limit=limit)

        listing_ids = [f.listing_id for f in favorites]
        if not listing_ids:
            return []

        listings_map = {
            lst.id: lst
            for lst in await fetch_listings_by_ids(
                self._session, listing_ids, is_active=True
            )
        }


        result = []
        for fav in favorites:
            listing = listings_map.get(fav.listing_id)
            if listing:
                result.append(
                    {
                        "favorite_id": fav.id,
                        "user_id": fav.user_id,
                        "listing_id": fav.listing_id,
                        "created_at": fav.created_at.isoformat()
                        if fav.created_at
                        else None,
                        "listing": {
                            "id": listing.id,
                            "source": listing.source,
                            "source_id": listing.source_id,
                            "property_type": listing.property_type,
                            "rent_type": listing.rent_type,
                            "deposit": listing.deposit,
                            "monthly_rent": listing.monthly_rent,
                            "address": listing.address,
                            "dong": listing.dong,
                            "detail_address": listing.detail_address,
                            "area_m2": float(listing.area_m2)
                            if listing.area_m2 is not None
                            else None,
                            "floor": listing.floor,
                            "total_floors": listing.total_floors,
                            "description": listing.description,
                            "latitude": float(listing.latitude)
                            if listing.latitude is not None
                            else None,
                            "longitude": float(listing.longitude)
                            if listing.longitude is not None
                            else None,
                        },
                    }
                )

        return result

    async def remove_favorite(self, user_id: str, listing_id: int) -> dict[str, object]:
        """Remove a listing from user favorites."""


        deleted = await delete_favorite(self._session, user_id, listing_id)

        if not deleted:
            return {
                "user_id": user_id,
                "listing_id": listing_id,
                "status": "not_found",
                "message": "Favorite not found",
            }

        return {
            "user_id": user_id,
            "listing_id": listing_id,
            "status": "removed",
            "message": "Listing removed from favorites",
        }
