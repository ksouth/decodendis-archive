"""FastAPI backend module."""

from .main import app
from .models import SearchRequest, SearchResponse

__all__ = ["app", "SearchRequest", "SearchResponse"]
