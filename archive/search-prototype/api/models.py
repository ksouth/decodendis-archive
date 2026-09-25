"""Request and response models for FastAPI."""

from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime


class SearchRequest(BaseModel):
    """Search request model."""

    query: str = Field(..., description="Search query")
    n_results: int = Field(default=10, ge=1, le=100, description="Number of results")
    exclude_unreviewed: bool = Field(
        default=False, description="Exclude unreviewed documents"
    )
    source_types: Optional[List[str]] = Field(
        default=None, description="Filter by source types"
    )
    include_context: bool = Field(
        default=False, description="Include context chunks"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "query": "disability support",
                "n_results": 10,
                "exclude_unreviewed": False,
                "source_types": ["pdf", "webpage"],
                "include_context": False,
            }
        }


class DocumentChunk(BaseModel):
    """A chunk of a document."""

    id: str
    text: str
    score: float = Field(description="Similarity score (0-1)")
    document_id: str
    page: Optional[int] = None


class DocumentResult(BaseModel):
    """A search result document."""

    id: str
    title: str
    url: str
    source: str
    document_type: str
    chunks: List[DocumentChunk]
    metadata: Optional[Dict[str, Any]] = None
    relevance_score: float = Field(description="Average relevance score")


class SearchResponse(BaseModel):
    """Search response model."""

    api_version: str
    query: str
    collection: str
    total_results: int
    results: List[DocumentResult]
    execution_time_ms: float

    class Config:
        json_schema_extra = {
            "example": {
                "api_version": "1.0.0",
                "query": "disability support",
                "collection": "documents",
                "total_results": 42,
                "results": [
                    {
                        "id": "doc_123",
                        "title": "Disability Support Guide",
                        "url": "https://example.com/guide",
                        "source": "government",
                        "document_type": "pdf",
                        "chunks": [
                            {
                                "id": "chunk_1",
                                "text": "Disability support includes...",
                                "score": 0.95,
                                "document_id": "doc_123",
                                "page": 1,
                            }
                        ],
                        "metadata": {},
                        "relevance_score": 0.92,
                    }
                ],
                "execution_time_ms": 125.5,
            }
        }


class DocumentDetailResponse(BaseModel):
    """Full document details."""

    id: str
    title: str
    content: str
    url: str
    source: str
    document_type: str
    scraped_at: datetime
    metadata: Optional[Dict[str, Any]] = None
    chunk_count: int


class APIInfo(BaseModel):
    """API information."""

    name: str = "SCRAPE - Document Search API"
    version: str = "1.0.0"
    description: str = "Semantic search over scraped documents using RAG"
    document_count: int
    chunk_count: int
    last_updated: datetime
    vector_db: str
    embedding_model: str
