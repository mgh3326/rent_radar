"""MCP tools for region management."""

from mcp.server.fastmcp import FastMCP

from src.config.region_codes import SIDO_SIGUNGU


def register_region_tools(mcp: FastMCP) -> None:
    """Register region-related tools on a FastMCP server."""

    @mcp.tool(name="list_regions")
    async def list_regions(
        sido: str | None = None,
        sigungu: str | None = None,
        format: str = "compact",
    ) -> dict[str, object]:
        """List available regions by sido (province) or sigungu (city).

        Args:
            sido: Filter by province name (e.g., "서울특별시", "경기도")
            sigungu: Filter by city name (e.g., "강남구", "종로구")
            format: Output format - "compact" (default) or "detailed"

        Returns:
            Region list with codes and names matching the filters.
        """

        regions = []
        for sido_name, sigungu_list in SIDO_SIGUNGU.items():
            if sido and sido_name != sido:
                continue

            for code, sigungu_name in sigungu_list:
                if sigungu and sigungu_name != sigungu:
                    continue

                if format == "compact":
                    regions.append(
                        {
                            "sido": sido_name,
                            "sigungu": sigungu_name,
                            "code": code,
                        }
                    )
                else:
                    regions.append(
                        {
                            "sido": sido_name,
                            "sigungu": sigungu_name,
                            "code": code,
                            "full_name": f"{sido_name} {sigungu_name}",
                        }
                    )

        return {
            "count": len(regions),
            "regions": regions,
        }

    @mcp.tool(name="search_regions")
    async def search_regions(
        query: str,
        limit: int = 20,
    ) -> dict[str, object]:
        """Search regions by partial name matching.

        Args:
            query: Search query (matches sido, sigungu, or full name)
            limit: Maximum number of results to return (default: 20)

        Returns:
            Matching regions with codes and names.
        """

        query_lower = query.lower()
        matches = []

        for sido_name, sigungu_list in SIDO_SIGUNGU.items():
            for code, sigungu_name in sigungu_list:
                full_name = f"{sido_name} {sigungu_name}"
                if (
                    query_lower in sido_name.lower()
                    or query_lower in sigungu_name.lower()
                    or query_lower in full_name.lower()
                ):
                    matches.append(
                        {
                            "sido": sido_name,
                            "sigungu": sigungu_name,
                            "code": code,
                            "full_name": full_name,
                        }
                    )

        return {
            "count": len(matches[:limit]),
            "regions": matches[:limit],
        }
