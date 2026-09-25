"""Website scraper using BeautifulSoup."""

import requests
from bs4 import BeautifulSoup
from typing import List, Dict, Any
from .base_scraper import BaseScraper, ScrapedDocument
from datetime import datetime
import logging
import chromadb
import os

logger = logging.getLogger(__name__)


class WebsiteScraper(BaseScraper):
    """Scrape structured HTML documents from websites."""

    def validate(self) -> bool:
        """Check if URL is accessible."""
        try:
            response = requests.head(self.url, timeout=self.timeout)
            return response.status_code < 400
        except Exception as e:
            logger.error(f"Validation failed for {self.url}: {e}")
            return False

    def scrape(self) -> List[ScrapedDocument]:
        """
        Scrape documents from website.

        Expects config like:
        {
            "url": "https://example.com",
            "selectors": {
                "documents": ".document",
                "title": "h1",
                "content": ".content"
            }
        }
        """
        documents = []

        try:
            response = requests.get(self.url, timeout=self.timeout)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, "html.parser")

            # Find all document containers
            doc_selector = self.selectors.get("documents", "article")
            doc_elements = soup.select(doc_selector)

            logger.info(f"Found {len(doc_elements)} documents at {self.url}")

            for element in doc_elements:
                try:
                    doc = self._extract_document(element)
                    if doc:
                        documents.append(doc)
                except Exception as e:
                    logger.warning(f"Failed to extract document: {e}")

        except requests.exceptions.RequestException as e:
            logger.error(f"Scraping failed for {self.url}: {e}")

        return documents

    def _extract_document(self, element) -> ScrapedDocument:
        """Extract a single document from HTML element."""
        title_selector = self.selectors.get("title", "h1")
        content_selector = self.selectors.get("content", "p")
        url_selector = self.selectors.get("url", "a")

        title_elem = element.select_one(title_selector)
        content_elem = element.select_one(content_selector)
        url_elem = element.select_one(url_selector)

        # Extract title (required)
        if not title_elem:
            return None

        title = title_elem.get_text(strip=True)
        if not title:
            return None

        # Extract content (fallback to element text if no content selector matches)
        if content_elem:
            content = content_elem.get_text(strip=True)
        else:
            content = element.get_text(strip=True)[:500]  # Use element's text, limit to 500 chars

        if not content:
            return None

        # Extract URL
        url = self.url
        if url_elem:
            url = url_elem.get("href", self.url)

        # Make relative URLs absolute
        if url.startswith("/"):
            from urllib.parse import urljoin
            url = urljoin(self.url, url)

        return ScrapedDocument(
            title=title,
            content=content,
            url=url,
            source=self.source,
            scraped_at=datetime.now(),
            document_type="webpage",
            metadata=self.extract_metadata(content),
        )
