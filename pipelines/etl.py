"""Batch document ETL pipeline for bulk ingestion from a directory."""

import asyncio
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Allow running as a standalone script from the project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from core.rag.ingestion import DocumentIngestionPipeline, SUPPORTED_EXTENSIONS

logger = logging.getLogger(__name__)


@dataclass
class ETLStats:
    """Aggregated statistics for an ETL run."""

    processed: int = 0
    failed: int = 0
    total_chunks: int = 0
    errors: list[str] = field(default_factory=list)
    start_time: float = field(default_factory=time.time)

    @property
    def duration_seconds(self) -> float:
        return time.time() - self.start_time

    def summary(self) -> str:
        return (
            f"ETL Summary: {self.processed} processed, {self.failed} failed, "
            f"{self.total_chunks} total chunks, {self.duration_seconds:.1f}s elapsed"
        )


async def run_etl(
    source_dir: Path,
    chunk_size: int = 512,
    chunk_overlap: int = 50,
    recursive: bool = True,
    dry_run: bool = False,
) -> ETLStats:
    """Batch-ingest all supported documents from a directory.

    Walks the source directory (optionally recursively), ingests each
    supported file, and logs progress and statistics.

    Args:
        source_dir: Path to the directory containing documents to ingest.
        chunk_size: Target token size per chunk (~4 chars/token).
        chunk_overlap: Overlap tokens between consecutive chunks.
        recursive: If True, walk subdirectories as well.
        dry_run: If True, discover files but do not actually ingest them.

    Returns:
        ETLStats with aggregated processing results.
    """
    from api.dependencies import get_ingestion_pipeline, get_retriever

    stats = ETLStats()

    if not source_dir.exists():
        logger.error("Source directory does not exist: %s", source_dir)
        stats.errors.append(f"Directory not found: {source_dir}")
        return stats

    # Discover files
    pattern = "**/*" if recursive else "*"
    all_files = [
        f for f in source_dir.glob(pattern)
        if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
    ]

    if not all_files:
        logger.warning("No supported files found in %s", source_dir)
        return stats

    logger.info(
        "ETL starting: %d files discovered in %s (dry_run=%s)",
        len(all_files),
        source_dir,
        dry_run,
    )

    if dry_run:
        for f in all_files:
            logger.info("[DRY RUN] Would ingest: %s", f.name)
        stats.processed = len(all_files)
        return stats

    # Build pipeline
    ingestion = get_ingestion_pipeline()

    for i, file_path in enumerate(all_files, 1):
        logger.info("[%d/%d] Ingesting %s ...", i, len(all_files), file_path.name)
        try:
            result = await ingestion.ingest_file(file_path)
            stats.processed += 1
            stats.total_chunks += result.chunks
            logger.info(
                "  -> OK: %d chunks (document_id=%s)", result.chunks, result.document_id
            )
        except Exception as e:
            stats.failed += 1
            error_msg = f"{file_path.name}: {e}"
            stats.errors.append(error_msg)
            logger.error("  -> FAILED: %s", error_msg)

    logger.info(stats.summary())
    return stats


def main() -> None:
    """CLI entry point for the ETL pipeline.

    Usage:
        python -m pipelines.etl [SOURCE_DIR] [--dry-run]

    Environment:
        Reads .env from the project root automatically.
    """
    import argparse

    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s | %(levelname)-8s | %(message)s",
    )

    parser = argparse.ArgumentParser(description="Batch document ingestion ETL pipeline")
    parser.add_argument(
        "source_dir",
        nargs="?",
        default="./data/sample_docs",
        help="Directory containing documents to ingest (default: ./data/sample_docs)",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=512,
        help="Target chunk size in tokens (default: 512)",
    )
    parser.add_argument(
        "--chunk-overlap",
        type=int,
        default=50,
        help="Overlap between chunks in tokens (default: 50)",
    )
    parser.add_argument(
        "--no-recursive",
        action="store_true",
        help="Do not walk subdirectories",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Discover files without ingesting them",
    )

    args = parser.parse_args()
    source_path = Path(args.source_dir).resolve()

    stats = asyncio.run(
        run_etl(
            source_dir=source_path,
            chunk_size=args.chunk_size,
            chunk_overlap=args.chunk_overlap,
            recursive=not args.no_recursive,
            dry_run=args.dry_run,
        )
    )

    if stats.errors:
        print("\nErrors encountered:")
        for err in stats.errors:
            print(f"  - {err}")

    sys.exit(0 if stats.failed == 0 else 1)


if __name__ == "__main__":
    main()
