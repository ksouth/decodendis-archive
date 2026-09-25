"""Vector database connection and operations."""

import chromadb
from typing import List, Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)


class VectorDatabase:
    """Wrapper around Chroma vector database."""

    def __init__(self, host: str = "localhost", port: int = 8000):
        """
        Initialize vector database connection.

        Args:
            host: Chroma server host
            port: Chroma server port
        """
        self.host = host
        self.port = port
        self.client = None
        self.collection = None

    async def connect(self):
        """Connect to Chroma (embedded or server)."""
        try:
            # Use persistent embedded Chroma
            self.client = chromadb.PersistentClient(path="./chroma_data")
            self.collection = self.client.get_or_create_collection(
                name="documents",
                metadata={"hnsw:space": "cosine"}
            )
            logger.info("Connected to persistent Chroma database")
        except Exception as e:
            logger.warning(f"Failed to connect to Chroma: {e}. Using mock mode.")
            self.collection = None  # Use mock mode

    async def disconnect(self):
        """Disconnect from database."""
        if self.client:
            try:
                self.client = None
                logger.info("Disconnected from Chroma")
            except Exception as e:
                logger.error(f"Error disconnecting: {e}")

    async def is_connected(self) -> bool:
        """Check if connected to database."""
        try:
            if self.collection is None:
                return False
            # Try a simple operation
            self.collection.count()
            return True
        except Exception as e:
            logger.error(f"Connection check failed: {e}")
            return False

    async def add_documents(
        self,
        documents: List[Dict[str, Any]],
    ) -> List[str]:
        """
        Add documents to the collection.

        Args:
            documents: List of dicts with keys:
                - id: unique document ID
                - title: document title
                - content: full document text
                - url: source URL
                - source: data source name
                - document_type: type of document
                - metadata: dict of additional metadata

        Returns:
            List of document IDs added
        """
        try:
            ids = []
            texts = []
            metadatas = []

            for doc in documents:
                doc_id = doc.get("id", f"doc_{len(ids)}")
                ids.append(doc_id)
                texts.append(doc.get("content", ""))

                metadata = doc.get("metadata", {})
                metadata.update({
                    "title": doc.get("title", ""),
                    "url": doc.get("url", ""),
                    "source": doc.get("source", ""),
                    "document_type": doc.get("document_type", ""),
                })
                metadatas.append(metadata)

            self.collection.add(
                ids=ids,
                documents=texts,
                metadatas=metadatas,
            )
            logger.info(f"Added {len(ids)} documents to collection")
            return ids

        except Exception as e:
            logger.error(f"Error adding documents: {e}")
            raise

    async def search(
        self,
        query: str,
        n_results: int = 10,
        source_types: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Search documents by semantic similarity.

        Args:
            query: Search query text
            n_results: Number of results to return
            source_types: Optional filter by source types

        Returns:
            List of matching documents with scores
        """
        try:
            # Return demo data if in mock mode (Chroma not available)
            if self.collection is None:
                return [
                    {
                        "id": "demo_1",
                        "title": "Demo Document 1",
                        "url": "https://example.com/doc1",
                        "source": "demo",
                        "document_type": "article",
                        "content": "This is a demo document. The API is running but no database is connected.",
                        "relevance_score": 0.95,
                        "chunks": [{
                            "id": "demo_1_chunk_0",
                            "text": "This is a demo document. The API is running but no database is connected.",
                            "score": 0.95,
                            "document_id": "demo_1",
                        }],
                        "metadata": {"query": query},
                    }
                ]

            where_filter = None
            if source_types:
                where_filter = {
                    "document_type": {"$in": source_types}
                }

            results = self.collection.query(
                query_texts=[query],
                n_results=n_results,
                where=where_filter,
                include=["documents", "metadatas", "distances"]
            )

            # Format results
            formatted = []
            if results and results["ids"]:
                for i, doc_id in enumerate(results["ids"][0]):
                    metadata = results["metadatas"][0][i] if results["metadatas"] else {}
                    distance = results["distances"][0][i] if results["distances"] else 0

                    # Convert distance to similarity score (0-1)
                    similarity = 1 - (distance / 2)

                    formatted.append({
                        "id": doc_id,
                        "title": metadata.get("title", ""),
                        "url": metadata.get("url", ""),
                        "source": metadata.get("source", ""),
                        "document_type": metadata.get("document_type", ""),
                        "content": results["documents"][0][i] if results["documents"] else "",
                        "relevance_score": similarity,
                        "chunks": [
                            {
                                "id": f"{doc_id}_chunk_0",
                                "text": results["documents"][0][i] if results["documents"] else "",
                                "score": similarity,
                                "document_id": doc_id,
                            }
                        ],
                        "metadata": metadata,
                    })

            logger.info(f"Search returned {len(formatted)} results for query: {query}")
            return formatted

        except Exception as e:
            logger.error(f"Search error: {e}")
            raise

    async def get_document(self, document_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve a specific document by ID.

        Args:
            document_id: Document ID to retrieve

        Returns:
            Document dict or None if not found
        """
        try:
            results = self.collection.get(
                ids=[document_id],
                include=["documents", "metadatas"]
            )

            if results["ids"]:
                metadata = results["metadatas"][0] if results["metadatas"] else {}
                return {
                    "id": document_id,
                    "title": metadata.get("title", ""),
                    "content": results["documents"][0] if results["documents"] else "",
                    "url": metadata.get("url", ""),
                    "source": metadata.get("source", ""),
                    "document_type": metadata.get("document_type", ""),
                    "scraped_at": metadata.get("scraped_at", ""),
                    "metadata": metadata,
                    "chunk_count": 1,
                }
            return None

        except Exception as e:
            logger.error(f"Error retrieving document: {e}")
            raise

    async def get_document_count(self) -> int:
        """Get total number of documents."""
        try:
            return self.collection.count()
        except Exception as e:
            logger.error(f"Error getting document count: {e}")
            return 0

    async def get_chunk_count(self) -> int:
        """Get total number of chunks (same as documents for now)."""
        try:
            return self.collection.count()
        except Exception as e:
            logger.error(f"Error getting chunk count: {e}")
            return 0

    async def delete_collection(self):
        """Delete entire collection."""
        try:
            if self.client:
                self.client.delete_collection(name="documents")
                self.collection = None
                logger.info("Deleted collection")
        except Exception as e:
            logger.error(f"Error deleting collection: {e}")
