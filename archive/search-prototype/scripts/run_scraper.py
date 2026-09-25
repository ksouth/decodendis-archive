#!/usr/bin/env python3
"""
Run the scraper manually to fetch and process documents.

Usage:
    python scripts/run_scraper.py                    # Run all sources
    python scripts/run_scraper.py --source "Name"    # Run specific source
    python scripts/run_scraper.py --dry-run          # Preview without saving
"""

import asyncio
import argparse
import yaml
import logging
from pathlib import Path
import sys

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper.website_scraper import WebsiteScraper
from processor.chunker import SemanticChunker
from processor.embedder import LocalEmbedder
import chromadb

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def main():
    """Main scraper runner."""
    parser = argparse.ArgumentParser(description="Run SCRAPE data scraper")
    parser.add_argument(
        "--source",
        type=str,
        help="Specific source to scrape (by name)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview without saving to database"
    )
    parser.add_argument(
        "--config",
        type=str,
        default="config/sources.yaml",
        help="Path to sources config file"
    )

    args = parser.parse_args()

    # Load configuration
    config_path = Path(args.config)
    if not config_path.exists():
        logger.error(f"Config file not found: {config_path}")
        return 1

    with open(config_path) as f:
        config = yaml.safe_load(f)

    sources = config.get("sources", [])
    processing_config = config.get("processing", {})

    # Filter sources
    if args.source:
        sources = [s for s in sources if s["name"] == args.source]
        if not sources:
            logger.error(f"Source not found: {args.source}")
            return 1

    # Only process enabled sources
    sources = [s for s in sources if s.get("enabled", True)]

    if not sources:
        logger.warning("No sources to scrape")
        return 0

    logger.info(f"Starting scraper with {len(sources)} source(s)")

    # Initialize processors
    chunker = SemanticChunker(
        chunk_size=processing_config.get("chunk_size", 512),
        overlap=processing_config.get("chunk_overlap", 100)
    )
    embedder = LocalEmbedder()  # Fast demo embeddings

    # Initialize persistent Chroma database
    chroma_client = chromadb.PersistentClient(path="./chroma_data")
    collection = chroma_client.get_or_create_collection(
        name="documents",
        metadata={"hnsw:space": "cosine"}
    )

    total_documents = 0
    total_chunks = 0

    # Process each source
    for source_config in sources:
        logger.info(f"\n{'='*60}")
        logger.info(f"Processing: {source_config['name']}")
        logger.info(f"{'='*60}")

        source_type = source_config.get("type", "website")

        try:
            if source_type == "website":
                scraper = WebsiteScraper(source_config)

                # Validate
                if not scraper.validate():
                    logger.error(f"Failed to validate source: {source_config['name']}")
                    continue

                # Scrape
                documents = scraper.scrape()
                logger.info(f"Scraped {len(documents)} documents")

                # Process each document
                for doc in documents:
                    # Chunk
                    chunks = chunker.chunk(doc.content)
                    logger.debug(f"Created {len(chunks)} chunks from: {doc.title}")

                    # Embed
                    embeddings = embedder.embed(chunks)
                    logger.debug(f"Generated {len(embeddings)} embeddings")

                    total_documents += 1
                    total_chunks += len(chunks)

                    if args.dry_run:
                        logger.info(f"[DRY-RUN] Would save: {doc.title}")
                    else:
                        # Save to persistent Chroma database
                        try:
                            import hashlib
                            doc_hash = hashlib.md5(f"{doc.url}{doc.title}".encode()).hexdigest()[:8]
                            collection.add(
                                ids=[f"{doc_hash}_{i}" for i in range(len(chunks))],
                                documents=chunks,
                                metadatas=[{
                                    "title": doc.title,
                                    "url": doc.url,
                                    "source": doc.source,
                                    "document_type": doc.document_type
                                } for _ in chunks]
                            )
                            logger.info(f"Saved: {doc.title} ({len(chunks)} chunks)")
                        except Exception as e:
                            logger.error(f"Failed to save {doc.title}: {e}")

            elif source_type == "pdf":
                logger.warning(f"PDF scraper not yet implemented")
            else:
                logger.warning(f"Unknown source type: {source_type}")

        except Exception as e:
            logger.error(f"Error processing {source_config['name']}: {e}", exc_info=True)

    logger.info(f"\n{'='*60}")
    logger.info(f"Scraping Complete!")
    logger.info(f"Total documents: {total_documents}")
    logger.info(f"Total chunks: {total_chunks}")
    logger.info(f"{'='*60}")

    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
