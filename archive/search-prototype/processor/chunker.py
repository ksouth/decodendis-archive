"""Document chunking strategies for RAG."""

from typing import List
import re


class SemanticChunker:
    """Split documents into semantic chunks (paragraphs, sentences)."""

    def __init__(self, chunk_size: int = 512, overlap: int = 100):
        """
        Initialize chunker.

        Args:
            chunk_size: Target size in characters (not exact)
            overlap: Character overlap between chunks
        """
        self.chunk_size = chunk_size
        self.overlap = overlap

    def chunk(self, text: str) -> List[str]:
        """
        Split text into semantic chunks.

        Tries to break at paragraph/sentence boundaries to preserve meaning.
        """
        # Remove extra whitespace
        text = re.sub(r"\s+", " ", text).strip()

        # Split into paragraphs
        paragraphs = text.split("\n")
        paragraphs = [p.strip() for p in paragraphs if p.strip()]

        chunks = []
        current_chunk = ""

        for paragraph in paragraphs:
            # If adding paragraph exceeds size, save chunk and start new
            if len(current_chunk) + len(paragraph) > self.chunk_size:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                current_chunk = paragraph
            else:
                if current_chunk:
                    current_chunk += " " + paragraph
                else:
                    current_chunk = paragraph

        # Add final chunk
        if current_chunk:
            chunks.append(current_chunk.strip())

        # Add overlap between chunks
        if self.overlap > 0:
            overlapped_chunks = []
            for i, chunk in enumerate(chunks):
                if i > 0:
                    # Add tail of previous chunk
                    prev_chunk = chunks[i - 1]
                    overlap_text = prev_chunk[-self.overlap:] if len(prev_chunk) > self.overlap else prev_chunk
                    overlapped_chunks.append(overlap_text + " " + chunk)
                else:
                    overlapped_chunks.append(chunk)
            chunks = overlapped_chunks

        return chunks


class TokenChunker:
    """Split by token count (requires tokenizer)."""

    def __init__(self, tokens_per_chunk: int = 256, overlap_tokens: int = 50):
        """
        Initialize token-based chunker.

        Args:
            tokens_per_chunk: Approximate tokens per chunk
            overlap_tokens: Token overlap between chunks
        """
        self.tokens_per_chunk = tokens_per_chunk
        self.overlap_tokens = overlap_tokens

    def chunk(self, text: str) -> List[str]:
        """
        Split text by approximate token count.

        Note: This is a simple word-based approximation.
        For production, use a real tokenizer (from transformers library).
        """
        words = text.split()

        # Rough approximation: 1 token ≈ 0.75 words
        words_per_chunk = int(self.tokens_per_chunk / 0.75)
        overlap_words = int(self.overlap_tokens / 0.75)

        chunks = []
        for i in range(0, len(words), words_per_chunk - overlap_words):
            chunk_words = words[i : i + words_per_chunk]
            chunks.append(" ".join(chunk_words))

        return chunks
