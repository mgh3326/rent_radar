"""MCP tools for listing recommendations."""

from decimal import Decimal

from mcp.server.fastmcp import FastMCP

from src.db.session import session_context
from src.services.recommendation_service import RecommendationService


def register_recommendation_tools(mcp: FastMCP) -> None:
    """Register recommendation-related tools on a FastMCP server."""

    @mcp.tool(name="recommend_listings")
    async def recommend_listings(
        region_code: str,
        dong: str | None = None,
        property_types: list[str] | None = None,
        rent_type: str | None = None,
        min_deposit: int | None = None,
        max_deposit: int | None = None,
        min_monthly_rent: int | None = None,
        max_monthly_rent: int | None = None,
        min_area: float | None = None,
        max_area: float | None = None,
        min_floor: int | None = None,
        max_floor: int | None = None,
        limit: int = 10,
    ) -> dict[str, object]:
        """오피스텔·빌라 매물 추천.

        현재 활성 매물을 기준으로, 같은 지역/유형 대비 ㎡당 환산월세가 얼마나 유리한지
        점수화하여 추천합니다.

        Args:
            region_code: 필수. 지역 코드 (예: "11110" 종로구)
            dong: 선택. 동 이름
            property_types: 선택. 매물 유형 목록 (기본값: ["villa", "officetel"])
            rent_type: 선택. 임대 유형 ("월세", "전세", "monthly", "jeonse")
            min_deposit: 선택. 최소 보증금
            max_deposit: 선택. 최대 보증금
            min_monthly_rent: 선택. 최소 월세
            max_monthly_rent: 선택. 최대 월세
            min_area: 선택. 최소 면적 (㎡)
            max_area: 선택. 최대 면적 (㎡)
            min_floor: 선택. 최소 층수
            max_floor: 선택. 최대 층수
            limit: 반환할 최대 매물 수 (기본값: 10)

        Returns:
            status: "success" | "needs_crawl" | "error"
            count: 추천 매물 수
            items: 추천 매물 목록 (각 항목에 rank, recommendation_score 포함)
            crawl_status: 데이터 갱신 상태
            crawl_message: 크롤링 필요 시 안내 메시지
        """
        async with session_context() as session:
            service = RecommendationService(session)
            result = await service.recommend_listings(
                region_code=region_code,
                dong=dong,
                property_types=property_types,
                rent_type=rent_type,
                min_deposit=min_deposit,
                max_deposit=max_deposit,
                min_monthly_rent=min_monthly_rent,
                max_monthly_rent=max_monthly_rent,
                min_area=Decimal(str(min_area)) if min_area is not None else None,
                max_area=Decimal(str(max_area)) if max_area is not None else None,
                min_floor=min_floor,
                max_floor=max_floor,
                limit=limit,
            )
            return result
