"""Data scraping module."""

from .base_scraper import BaseScraper, ScrapedDocument
from .website_scraper import WebsiteScraper

__all__ = ["BaseScraper", "ScrapedDocument", "WebsiteScraper"]
