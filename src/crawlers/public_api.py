from __future__ import annotations

"""Public data portal crawler for apartment rent real trades."""

import logging

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Final

import httpx
from bs4 import BeautifulSoup
from bs4.element import Tag

from src.config import Settings, get_settings
from src.crawlers.base import CrawlResult
from src.db.repositories import RealTradeUpsert

logger = logging.getLogger(__name__)


PROPERTY_TYPE_CONFIG: Final = {
    "apt": {
        "endpoint_suffix": "RTMSDataSvcAptRent/getRTMSDataSvcAptRent",
        "name_tags": ("아파트", "aptNm"),
    },
    "villa": {
        "endpoint_suffix": "RTMSDataSvcRHRent/getRTMSDataSvcRHRent",
        "name_tags": ("연립다세대", "mhouseNm"),
    },
    "officetel": {
        "endpoint_suffix": "RTMSDataSvcOffiRent/getRTMSDataSvcOffiRent",
        "name_tags": ("오피스텔", "offiNm"),
    },
    "house": {
        "endpoint_suffix": "RTMSDataSvcSHRent/getRTMSDataSvcSHRent",
        "name_tags": ("단독다가구", "houseNm"),
    },
    "apt_sale": {
        "endpoint_suffix": "RTMSDataSvcAptTrade/getRTMSDataSvcAptTrade",
        "name_tags": ("아파트", "aptNm"),
        "trade_category": "sale",
    },
    "villa_sale": {
        "endpoint_suffix": "RTMSDataSvcRHTrade/getRTMSDataSvcRHTrade",
        "name_tags": ("연립다세대", "mhouseNm"),
        "trade_category": "sale",
    },
    "officetel_sale": {
        "endpoint_suffix": "RTMSDataSvcOffiTrade/getRTMSDataSvcOffiTrade",
        "name_tags": ("오피스텔", "offiNm"),
        "trade_category": "sale",
    },
    "house_sale": {
        "endpoint_suffix": "RTMSDataSvcSHTrade/getRTMSDataSvcSHTrade",
        "name_tags": ("단독다가구", "houseNm"),
        "trade_category": "sale",
    },
}


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


def _shift_month(year: int, month: int, offset: int = 0) -> tuple[int, int]:
    """Shift year/month by offset months (negative for past)."""
    year_offset, month = divmod(month - 1 - offset, 12)
    year += year_offset
    month += 1
    return year, month


class PublicApiCrawler:
    """Crawler for MOLIT public API real trade data."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        region_codes: list[str] | None = None,
        property_types: list[str] | None = None,
        start_year_month: str | None = None,
        end_year_month: str | None = None,
    ):
        self._settings = settings or get_settings()
        self._property_types = property_types or self._settings.target_property_types
        self._region_codes = region_codes or self._settings.target_region_codes
        self._start_year_month = start_year_month
        self._end_year_month = end_year_month

    def _target_months(self) -> list[str]:
        """Generate target months in YYYYMM format."""
        if self._start_year_month:
            start_ym = int(self._start_year_month[:6])
            if self._end_year_month:
                end_ym = int(self._end_year_month[:6])
            else:
                end_ym = start_ym
            months: list[str] = []
            ym = start_ym
            while ym <= end_ym:
                year = ym // 100
                month = ym % 100
                months.append(f"{year}{month:02d}")
                month += 1
                if month > 12:
                    month = 1
                    year += 1
                ym = year * 100 + month
            return months

        now = datetime.now(UTC)
        months = []
        for offset in range(self._settings.public_data_fetch_months):
            year, month = _shift_month(now.year, now.month, offset)
            months.append(f"{year}{month:02d}")
        return months

    async def _request_xml(
        self,
        client,
        property_type: str,
        region_code: str,
        deal_ymd: str,
        page_no: int = 1,
    ) -> str:
        """Fetch XML response from public API."""
        config = PROPERTY_TYPE_CONFIG.get(property_type, {})
        endpoint_suffix = config.get("endpoint_suffix", "")
        base_url = self._settings.public_data_api_base_url

        params = {
            "serviceKey": self._settings.public_data_api_key,
            "LAWD_CD": region_code,
            "DEAL_YMD": deal_ymd,
            "pageNo": str(page_no),
            "numOfRows": "1000",
        }

        url = f"{base_url}/{endpoint_suffix}"
        response = await client.get(url, params=params)
        response.raise_for_status()
        return response.text

    def _parse_item(
        self, property_type: str, region_code: str, item: Tag
    ) -> RealTradeUpsert | None:
        config = PROPERTY_TYPE_CONFIG.get(property_type)
        if config is None:
            return None
        trade_category = config.get("trade_category", "rent")

        contract_year = _to_int(_extract_text(item, "년", "dealYear"), 0)
        contract_month = _to_int(_extract_text(item, "월", "dealMonth"), 0)
        contract_day = _to_int(_extract_text(item, "일", "dealDay"), 1)

        # Fixed bug: "거래금액" for sale, "보증금액" for rent
        sales_price_field = "거래금액" if trade_category == "sale" else "보증금액"

        deposit = _to_int(_extract_text(item, sales_price_field, "deposit"), 0)

        building_name = _extract_text(item, *config["name_tags"]) or ""
        dong = _extract_text(item, "법정동", "umdNm") or ""
        apt_name = _extract_text(item, *config["name_tags"]) or ""

        monthly_rent = _to_int(_extract_text(item, "월세금액", "monthlyRent"), 0)

        return RealTradeUpsert(
            property_type=property_type,
            rent_type="monthly" if monthly_rent > 0 else "jeonse",
            region_code=region_code,
            dong=dong,
            apt_name=apt_name,
            deposit=deposit,
            monthly_rent=monthly_rent,
            area_m2=_to_decimal(_extract_text(item, "전용면적", "excluUseAr")),
            floor=_to_int(_extract_text(item, "층", "floor"), 0),
            contract_year=contract_year,
            contract_month=contract_month,
            contract_day=contract_day,
            trade_category=trade_category,
        )

    def _parse_xml(
        self, property_type: str, region_code: str, xml_text: str
    ) -> list[RealTradeUpsert]:
        soup = BeautifulSoup(xml_text, "xml")
        items = soup.find_all("item")
        parsed: list[RealTradeUpsert] = []
        for item in items:
            row = self._parse_item(property_type, region_code, item)
            if row is not None:
                parsed.append(row)
        return parsed

    async def run(self) -> CrawlResult[RealTradeUpsert]:
        """Fetch and parse official real trade rows for target regions/months."""

        if not self._settings.public_data_api_key:
            return self._get_mock_data()

        all_rows: list[RealTradeUpsert] = []
        errors: list[str] = []
        timeout = httpx.Timeout(self._settings.public_data_request_timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout) as client:
            for property_type in self._property_types:
                for region_code in self._region_codes:
                    for deal_ymd in self._target_months():
                        page_no = 1
                        while True:
                            try:
                                xml_text = await self._request_xml(
                                    client,
                                    property_type,
                                    region_code,
                                    deal_ymd,
                                    page_no,
                                )
                                rows = self._parse_xml(
                                    property_type, region_code, xml_text
                                )
                                if not rows:
                                    break
                                all_rows.extend(rows)
                                if len(rows) < 1000:
                                    break
                                page_no += 1
                            except httpx.HTTPStatusError as e:
                                error_msg = (
                                    f"HTTP {e.response.status_code} error for "
                                    f"property_type={property_type}, region_code={region_code}, "
                                    f"deal_ymd={deal_ymd}, page_no={page_no}"
                                )
                                logger.warning(error_msg)
                                errors.append(error_msg)
                                break
                            except Exception as e:
                                error_msg = (
                                    f"Unexpected error for "
                                    f"property_type={property_type}, region_code={region_code}, "
                                    f"deal_ymd={deal_ymd}, page_no={page_no}: {str(e)}"
                                )
                                logger.warning(error_msg)
                                errors.append(error_msg)
                                break

        return CrawlResult(count=len(all_rows), rows=all_rows, errors=errors)

    def _get_mock_data(self) -> CrawlResult[RealTradeUpsert]:
        """Return mock real trade data for testing without API key."""

        now = datetime.now(UTC)
        mock_rows: list[RealTradeUpsert] = []

        for property_type in self._property_types:
            for region_code in self._region_codes:
                for offset in range(self._settings.public_data_fetch_months):
                    year, month = _shift_month(now.year, now.month, offset)

                    building_prefix = (
                        "테스트연립"
                        if property_type == "villa"
                        else "테스트오피스텔"
                        if property_type == "officetel"
                        else "테스트단독"
                        if property_type == "house"
                        else "테스트아파트"
                    )

                    for i in range(3):
                        mock_rows.append(
                            RealTradeUpsert(
                                property_type=property_type,
                                rent_type="jeonse" if i % 2 == 0 else "monthly",
                                region_code=region_code,
                                dong=f"법정동{i + 1}",
                                apt_name=f"{building_prefix}{i + 1}",
                                deposit=50_000 * (i + 1) * 10000,
                                monthly_rent=50 * (i + 1) * 10000 if i % 2 == 1 else 0,
                                area_m2=Decimal(f"{80 + i * 10}.0"),
                                floor=5 + i,
                                contract_year=year,
                                contract_month=month,
                                contract_day=15,
                            )
                        )

        return CrawlResult(count=len(mock_rows), rows=mock_rows, errors=[])
