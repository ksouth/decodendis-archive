"""FastAPI backend for document search."""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import time
import os
from datetime import datetime

from .models import (
    SearchRequest,
    SearchResponse,
    DocumentResult,
    DocumentDetailResponse,
    APIInfo,
    DocumentChunk,
)
from .database import VectorDatabase


# Initialize database connection
db = None

# Create FastAPI app
app = FastAPI(
    title="SCRAPE - Document Search API",
    description="Semantic search over scraped documents using RAG",
    version="1.0.0",
)

# Startup
@app.on_event("startup")
async def startup():
    global db
    db = VectorDatabase()
    await db.connect()

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Change to specific origins in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    """Root endpoint."""
    return {"message": "SCRAPE API running"}

@app.get("/healthz")
async def healthz():
    """Health check endpoint."""
    return {"status": "ok"}


@app.get("/readyz")
async def readyz():
    """Readiness check endpoint."""
    try:
        if db is None:
            return {"status": "not_ready", "reason": "Database not initialized"}
        is_ready = await db.is_connected()
        return {"status": "ready" if is_ready else "not_ready"}
    except Exception as e:
        return {"status": "not_ready", "reason": str(e)}


@app.get("/v1/info", response_model=APIInfo)
async def get_info():
    """Get API information and statistics."""
    if db is None:
        raise HTTPException(status_code=503, detail="Database not initialized")

    doc_count = await db.get_document_count()
    chunk_count = await db.get_chunk_count()

    return APIInfo(
        document_count=doc_count,
        chunk_count=chunk_count,
        last_updated=datetime.now(),
        vector_db="Chroma",
        embedding_model="all-MiniLM-L6-v2",
    )


@app.post("/v1/search", response_model=SearchResponse)
async def search(request: SearchRequest):
    """
    Search documents using semantic similarity.

    Query the indexed documents with natural language.
    Returns matching documents with relevance scores.
    """
    if db is None:
        raise HTTPException(status_code=503, detail="Database not initialized")

    start_time = time.time()

    try:
        # Search vector database
        results = await db.search(
            query=request.query,
            n_results=request.n_results,
            source_types=request.source_types,
        )

        # Format results
        formatted_results = []
        for doc_result in results:
            # Convert chunk results to DocumentChunk objects
            chunks = [
                DocumentChunk(
                    id=chunk["id"],
                    text=chunk["text"],
                    score=float(chunk["score"]),
                    document_id=chunk["document_id"],
                    page=chunk.get("page"),
                )
                for chunk in doc_result.get("chunks", [])
            ]

            doc = DocumentResult(
                id=doc_result["id"],
                title=doc_result["title"],
                url=doc_result["url"],
                source=doc_result["source"],
                document_type=doc_result["document_type"],
                chunks=chunks,
                metadata=doc_result.get("metadata"),
                relevance_score=doc_result.get("relevance_score", 0.0),
            )
            formatted_results.append(doc)

        execution_time = (time.time() - start_time) * 1000  # Convert to ms

        return SearchResponse(
            api_version="1.0.0",
            query=request.query,
            collection="documents",
            total_results=len(formatted_results),
            results=formatted_results,
            execution_time_ms=execution_time,
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")


@app.get("/v1/documents/{document_id}", response_model=DocumentDetailResponse)
async def get_document(document_id: str):
    """Retrieve full document by ID."""
    if db is None:
        raise HTTPException(status_code=503, detail="Database not initialized")

    try:
        doc = await db.get_document(document_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")

        return DocumentDetailResponse(
            id=doc["id"],
            title=doc["title"],
            content=doc["content"],
            url=doc["url"],
            source=doc["source"],
            document_type=doc["document_type"],
            scraped_at=datetime.fromisoformat(doc["scraped_at"]),
            metadata=doc.get("metadata"),
            chunk_count=doc.get("chunk_count", 0),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving document: {str(e)}")


@app.on_event("startup")
async def startup():
    """Startup event."""
    print("SCRAPE API starting...")


@app.on_event("shutdown")
async def shutdown():
    """Shutdown event."""
    print("SCRAPE API shutting down...")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
