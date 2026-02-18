"""Crawler implementations."""

from src.crawlers.base import CrawlResult
from src.crawlers.naver import NaverCrawler
from src.crawlers.zigbang import ZigbangCrawler

__all__ = ["CrawlResult", "NaverCrawler", "ZigbangCrawler"]
