"""Abstract base scraper class for all data sources."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Dict, Any


@dataclass
class ScrapedDocument:
    """Represents a scraped document."""

    title: str
    content: str
    url: str
    source: str
    scraped_at: datetime
    document_type: str = "document"
    metadata: Dict[str, Any] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "title": self.title,
            "content": self.content,
            "url": self.url,
            "source": self.source,
            "scraped_at": self.scraped_at.isoformat(),
            "document_type": self.document_type,
            "metadata": self.metadata or {},
        }


class BaseScraper(ABC):
    """Abstract base class for all scrapers."""

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize scraper with configuration.

        Args:
            config: Configuration dict with keys like 'url', 'selectors', 'timeout'
        """
        self.config = config
        self.url = config.get("url")
        self.selectors = config.get("selectors", {})
        self.timeout = config.get("timeout", 30)
        self.source = config.get("name", "unknown")

    @abstractmethod
    def scrape(self) -> List[ScrapedDocument]:
        """
        Scrape documents from source.

        Returns:
            List of ScrapedDocument objects
        """
        pass

    @abstractmethod
    def validate(self) -> bool:
        """Validate configuration and connectivity."""
        pass

    def extract_metadata(self, content: str) -> Dict[str, Any]:
        """
        Extract metadata from content (to be overridden by subclasses).

        Args:
            content: Raw document content

        Returns:
            Dictionary of metadata
        """
        return {
            "scrape_source": self.source,
            "scraped_at": datetime.now().isoformat(),
        }
