"""Generate region_codes.py from MOLIT RegionalCode API.

Usage:
    python scripts/generate_region_codes.py
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from pathlib import Path

import httpx
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

API_ENDPOINT = "https://apis.data.go.kr/1613000/RegionalCode/getRegionalCode"
OUTPUT_FILE = Path("src/config/region_codes.py")


class Settings(BaseSettings):
    """Settings for region code generation script."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    public_data_api_key: str = ""


async def fetch_page(
    client: httpx.AsyncClient, service_key: str, page_no: int, num_of_rows: int
) -> dict:
    params = {
        "serviceKey": service_key,
        "pageNo": str(page_no),
        "numOfRows": str(num_of_rows),
        "dataType": "JSON",
    }

    response = await client.get(API_ENDPOINT, params=params)
    response.raise_for_status()
    return response.json()


async def fetch_all_region_codes(service_key: str) -> list[dict]:
    all_items = []
    page_no = 1
    num_of_rows = 1000

    timeout = httpx.Timeout(30.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        while True:
            logger.info(f"Fetching page {page_no}...")
            data = await fetch_page(client, service_key, page_no, num_of_rows)

            logger.info(f"Full API response: {data}")

            error = data.get("Error")
            if error:
                logger.error(f"API returned error: {error}")
                break

            header = data.get("header", {})

            result_code = header.get("resultCode") if header else None
            result_msg = header.get("resultMsg") if header else None

            if result_code and result_code != "00":
                logger.error(f"API error code {result_code}: {result_msg}")
                break

            body = data.get("body", {})
            items = body.get("items", []) if isinstance(body, dict) else []

            total_count = body.get("totalCount", 0) if isinstance(body, dict) else 0

            logger.info(f"Items on page {page_no}: {len(items)} (total: {total_count})")

            if not items:
                break

            all_items.extend(items)

            total_count = body.get("totalCount", 0)
            fetched_count = len(all_items)
            logger.info(
                f"  Fetched {len(items)} items (total: {fetched_count}/{total_count})"
            )

            if fetched_count >= total_count or len(items) < num_of_rows:
                break

            page_no += 1

            await asyncio.sleep(0.1)

    logger.info(f"Total items fetched: {len(all_items)}")
    return all_items


def parse_region_data(items: list[dict]) -> dict[str, list[tuple[str, str]]]:
    sido_dict = defaultdict(list)

    for item in items:
        ctprvn_cd = item.get("ctprvnCd") or item.get("ctpv_cd") or item.get("sido_cd")
        sgg_cd = item.get("sggCd") or item.get("sgg_cd")
        sgg_nm = item.get("sggNm") or item.get("sgg_nm")

        if not ctprvn_cd or not sgg_cd or not sgg_nm:
            logger.warning(f"Skipping item with missing fields: {item}")
            continue

        province_name = get_province_name(ctprvn_cd)
        if not province_name:
            continue

        sido_dict[province_name].append((sgg_cd, sgg_nm))

    return dict(sido_dict)


def get_province_name(code: str) -> str | None:
    province_mapping = {
        "11": "서울특별시",
        "26": "부산광역시",
        "27": "대구광역시",
        "28": "인천광역시",
        "29": "광주광역시",
        "30": "대전광역시",
        "31": "울산광역시",
        "36": "세종특별자치시",
        "41": "경기도",
        "42": "강원특별자치도",
        "43": "충청북도",
        "44": "충청남도",
        "45": "전북특별자치도",
        "46": "전라남도",
        "47": "경상북도",
        "48": "경상남도",
        "50": "제주특별자치도",
    }

    return province_mapping.get(code)


def generate_region_codes_python(sido_dict: dict[str, list[tuple[str, str]]]) -> str:
    all_codes: list[str] = []
    for province, districts in sido_dict.items():
        for code, _ in districts:
            all_codes.append(f'"{code}"')

    all_codes.sort()

    sido_lines = ["SIDO_SIGUNGU: dict[str, list[tuple[str, str]]] = {"]
    sorted_provinces = sorted(sido_dict.keys())

    for province in sorted_provinces:
        sido_lines.append(f'    "{province}": [')
        districts = sorted(sido_dict[province], key=lambda x: x[0])
        for code, name in districts:
            sido_lines.append(f'        ("{code}", "{name}"),')
        sido_lines.append("    ],")

    sido_lines.append("}")

    reverse_lines = [
        "# Reverse lookup: code -> full name (Si-Do + Si/Gun/Gu)",
        "REGION_CODE_TO_NAME: dict[str, str] = {",
        "    code: f'{sido} {name}'",
        "    for sido, districts in SIDO_SIGUNGU.items()",
        "    for code, name in districts",
        "}",
    ]

    helper_lines = [
        "",
        "",
        "def is_valid_region_code(region_code: str) -> bool:",
        '    """Check if a 5-digit region code is valid."""',
        "    return region_code in REGION_CODE_TO_NAME",
    ]

    sections = [
        '"""Korean administrative district codes (LAWD_CD) for MOLIT public API.\n'
        "\n"
        "This module provides the mapping of 5-digit LAWD_CD codes to Si/Gun/Gu names\n"
        "across all 17 special cities, metropolitan cities, and provinces in South Korea.\n"
        '"""',
        "",
        "from typing import Literal",
        "",
        "# Type alias for valid region codes",
        "RegionCode = Literal[",
        *sorted(all_codes),
        "]",
        "",
        "",
        "# Si/Do level groupings with Si/Gun/Gu subdivisions",
        *sido_lines,
        "",
        "",
        *reverse_lines,
        *helper_lines,
    ]

    return "\n".join(sections)


async def main() -> None:
    logger.info("Fetching region codes from MOLIT API...")

    try:
        settings = Settings()
    except Exception as e:
        logger.error(f"Failed to load settings: {e}")
        return

    service_key = settings.public_data_api_key

    if not service_key:
        logger.error(
            "PUBLIC_DATA_API_KEY not found in settings. Please set it in .env file."
        )
        return

    try:
        items = await fetch_all_region_codes(service_key)
        sido_dict = parse_region_data(items)

        if not sido_dict:
            logger.error("No region codes parsed from API response")
            return

        python_code = generate_region_codes_python(sido_dict)
        OUTPUT_FILE.write_text(python_code, encoding="utf-8")
        logger.info(f"Successfully wrote {OUTPUT_FILE}")

        total_districts = sum(len(districts) for districts in sido_dict.values())
        logger.info(f"Summary: {len(sido_dict)} provinces, {total_districts} districts")

    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error: {e.response.status_code} - {e.response.text}")
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)


if __name__ == "__main__":
    asyncio.run(main())
