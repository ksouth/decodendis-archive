"""Text embedding generators."""

from abc import ABC, abstractmethod
from typing import List
import numpy as np
import os


class BaseEmbedder(ABC):
    """Abstract base for embedding generators."""

    @abstractmethod
    def embed(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for texts."""
        pass


class LocalEmbedder(BaseEmbedder):
    """Generate embeddings using local sentence-transformers model."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        """
        Initialize with local embedding model.

        Models:
        - all-MiniLM-L6-v2: Fast, lightweight (~22MB)
        - all-mpnet-base-v2: Better quality, slower (~438MB)
        - distilbert-base-uncased: Even smaller

        Args:
            model_name: HuggingFace model identifier
        """
        try:
            from sentence_transformers import SentenceTransformer

            self.model = SentenceTransformer(model_name)
        except ImportError:
            raise ImportError(
                "Install sentence-transformers: pip install sentence-transformers"
            )

    def embed(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for texts (FREE, runs locally)."""
        embeddings = self.model.encode(texts, convert_to_numpy=True)
        return [embedding.tolist() for embedding in embeddings]


class OpenAIEmbedder(BaseEmbedder):
    """Generate embeddings using OpenAI API."""

    def __init__(self, model: str = "text-embedding-3-small"):
        """
        Initialize with OpenAI embedding model.

        Models:
        - text-embedding-3-small: $0.02 per 1M tokens (recommended)
        - text-embedding-3-large: $0.13 per 1M tokens

        Args:
            model: OpenAI model identifier
        """
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable not set")

        try:
            from openai import OpenAI

            self.client = OpenAI(api_key=api_key)
            self.model = model
        except ImportError:
            raise ImportError("Install openai: pip install openai")

    def embed(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings via OpenAI (COSTS MONEY)."""
        # Batch requests for efficiency
        embeddings = []
        batch_size = 100

        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            response = self.client.embeddings.create(
                model=self.model, input=batch
            )
            for item in response.data:
                embeddings.append(item.embedding)

        return embeddings


class DummyEmbedder(BaseEmbedder):
    """Dummy embedder for testing (generates random vectors)."""

    def __init__(self, dim: int = 384):
        self.dim = dim

    def embed(self, texts: List[str]) -> List[List[float]]:
        """Generate random embeddings (FOR TESTING ONLY)."""
        return [
            np.random.randn(self.dim).tolist() for _ in texts
        ]
