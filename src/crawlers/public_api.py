"""Public data portal crawler for apartment rent real trades."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

import httpx
from bs4 import BeautifulSoup
from bs4.element import Tag

from src.config import Settings, get_settings
from src.crawlers.base import CrawlResult
from src.db.repositories import RealTradeUpsert


def _to_int(value: str | None, default: int = 0) -> int:
    if not value:
        return default
    cleaned = value.replace(",", "").replace(" ", "").replace("-", "")
    if cleaned == "":
        return default
    try:
        return int(cleaned)
    except ValueError:
        return default


def _to_decimal(value: str | None) -> Decimal | None:
    if not value:
        return None
    cleaned = value.replace(",", "").replace(" ", "")
    if cleaned == "":
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _extract_text(item: Tag, *candidates: str) -> str | None:
    for candidate in candidates:
        found = item.find(candidate)
        if found and found.text is not None:
            text = str(found.text).strip()
            if text:
                return text
    return None


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    shifted_year = year
    shifted_month = month
    for _ in range(delta):
        shifted_month -= 1
        if shifted_month < 1:
            shifted_month = 12
            shifted_year -= 1
    return shifted_year, shifted_month


class PublicApiCrawler:
    """Crawler for MOLIT apartment rent real-trade API."""

    def __init__(self) -> None:
        self._settings: Settings = get_settings()

    def _target_months(self) -> list[str]:
        now = datetime.now(UTC)
        months: list[str] = []
        for offset in range(self._settings.public_data_fetch_months):
            year, month = _shift_month(now.year, now.month, offset)
            months.append(f"{year:04d}{month:02d}")
        return months

    async def _request_xml(
        self, client: httpx.AsyncClient, lawd_cd: str, deal_ymd: str, page_no: int
    ) -> str:
        params = {
            "serviceKey": self._settings.public_data_api_key,
            "LAWD_CD": lawd_cd,
            "DEAL_YMD": deal_ymd,
            "pageNo": page_no,
            "numOfRows": 1000,
        }
        response = await client.get(
            self._settings.public_data_api_endpoint, params=params
        )
        _ = response.raise_for_status()
        return response.text

    def _parse_item(self, region_code: str, item: Tag) -> RealTradeUpsert | None:
        contract_year = _to_int(_extract_text(item, "년", "dealYear"), 0)
        contract_month = _to_int(_extract_text(item, "월", "dealMonth"), 0)
        contract_day = _to_int(_extract_text(item, "일", "dealDay"), 1)
        if contract_year <= 0 or contract_month <= 0:
            return None

        deposit = _to_int(_extract_text(item, "보증금액", "deposit"), 0)
        monthly_rent = _to_int(_extract_text(item, "월세금액", "monthlyRent"), 0)

        return RealTradeUpsert(
            property_type="apt",
            rent_type="monthly" if monthly_rent > 0 else "jeonse",
            region_code=region_code,
            dong=_extract_text(item, "법정동", "umdNm"),
            apt_name=_extract_text(item, "아파트", "aptNm"),
            deposit=deposit,
            monthly_rent=monthly_rent,
            area_m2=_to_decimal(_extract_text(item, "전용면적", "excluUseAr")),
            floor=_to_int(_extract_text(item, "층", "floor"), 0) or None,
            contract_year=contract_year,
            contract_month=contract_month,
            contract_day=contract_day,
        )

    def _parse_xml(self, region_code: str, xml_text: str) -> list[RealTradeUpsert]:
        soup = BeautifulSoup(xml_text, "xml")
        items = soup.find_all("item")
        parsed: list[RealTradeUpsert] = []
        for item in items:
            row = self._parse_item(region_code, item)
            if row is not None:
                parsed.append(row)
        return parsed

    async def run(self) -> CrawlResult[RealTradeUpsert]:
        """Fetch and parse official real trade rows for target regions/months."""

        if not self._settings.public_data_api_key:
            return self._get_mock_data()

        all_rows: list[RealTradeUpsert] = []
        timeout = httpx.Timeout(self._settings.public_data_request_timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout) as client:
            for region_code in self._settings.target_region_codes:
                for deal_ymd in self._target_months():
                    page_no = 1
                    while True:
                        xml_text = await self._request_xml(
                            client, region_code, deal_ymd, page_no
                        )
                        rows = self._parse_xml(region_code, xml_text)
                        if not rows:
                            break
                        all_rows.extend(rows)
                        if len(rows) < 1000:
                            break
                        page_no += 1

        return CrawlResult(count=len(all_rows), rows=all_rows)

    def _get_mock_data(self) -> CrawlResult[RealTradeUpsert]:
        """Return mock real trade data for testing without API key."""

        now = datetime.now(UTC)
        mock_rows: list[RealTradeUpsert] = []

        for region_code in self._settings.target_region_codes:
            for offset in range(self._settings.public_data_fetch_months):
                year, month = _shift_month(now.year, now.month, offset)

                for i in range(3):
                    mock_rows.append(
                        RealTradeUpsert(
                            property_type="apt",
                            rent_type="jeonse" if i % 2 == 0 else "monthly",
                            region_code=region_code,
                            dong=f"법정동{i + 1}",
                            apt_name=f"테스트아파트{i + 1}",
                            deposit=50_000 * (i + 1) * 10000,
                            monthly_rent=50 * (i + 1) * 10000 if i % 2 == 1 else 0,
                            area_m2=Decimal(f"{80 + i * 10}.0"),
                            floor=5 + i,
                            contract_year=year,
                            contract_month=month,
                            contract_day=15,
                        )
                    )

        return CrawlResult(count=len(mock_rows), rows=mock_rows)
