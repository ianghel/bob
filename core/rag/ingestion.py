"""Document ingestion pipeline for the RAG knowledge base."""

import logging
import uuid
from pathlib import Path
from typing import Optional

from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import (
    PyPDFLoader,
    TextLoader,
    UnstructuredMarkdownLoader,
    Docx2txtLoader,
)
from langchain_core.documents import Document

from core.rag.retriever import ChromaRetriever

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {
    ".pdf": "pdf",
    ".txt": "text",
    ".md": "markdown",
    ".docx": "docx",
}


class IngestionResult:
    """Result of an ingestion operation."""

    def __init__(
        self,
        document_id: str,
        filename: str,
        chunks: int,
        format: str,
    ) -> None:
        self.document_id = document_id
        self.filename = filename
        self.chunks = chunks
        self.format = format

    def __repr__(self) -> str:
        return (
            f"IngestionResult(document_id={self.document_id!r}, "
            f"filename={self.filename!r}, chunks={self.chunks}, format={self.format!r})"
        )


class DocumentIngestionPipeline:
    """Pipeline to load, chunk and store documents into ChromaDB.

    Supports PDF, TXT, Markdown and DOCX formats. Documents are split
    using a recursive character splitter with configurable chunk size
    and overlap, then stored in the vector store via ChromaRetriever.
    """

    def __init__(
        self,
        retriever: ChromaRetriever,
        chunk_size: int = 512,
        chunk_overlap: int = 50,
    ) -> None:
        """Initialize the ingestion pipeline.

        Args:
            retriever: ChromaRetriever instance to store chunks.
            chunk_size: Target token count per chunk (approximate).
            chunk_overlap: Number of overlapping tokens between chunks.
        """
        self.retriever = retriever
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size * 4,  # ~4 chars per token
            chunk_overlap=chunk_overlap * 4,
            separators=["\n\n", "\n", " ", ""],
        )
        logger.info(
            "DocumentIngestionPipeline ready (chunk_size=%d, overlap=%d)",
            chunk_size,
            chunk_overlap,
        )

    def _load_document(self, file_path: Path) -> list[Document]:
        """Load a document from disk using the appropriate loader.

        Args:
            file_path: Path to the file to load.

        Returns:
            List of LangChain Document objects.

        Raises:
            ValueError: If the file extension is not supported.
        """
        ext = file_path.suffix.lower()
        if ext == ".pdf":
            loader = PyPDFLoader(str(file_path))
        elif ext == ".txt":
            loader = TextLoader(str(file_path), encoding="utf-8")
        elif ext == ".md":
            loader = UnstructuredMarkdownLoader(str(file_path))
        elif ext == ".docx":
            loader = Docx2txtLoader(str(file_path))
        else:
            raise ValueError(
                f"Unsupported file type: {ext}. "
                f"Supported: {list(SUPPORTED_EXTENSIONS.keys())}"
            )
        return loader.load()

    async def ingest_file(
        self,
        file_path: Path,
        document_id: Optional[str] = None,
        metadata: Optional[dict] = None,
        tenant_id: Optional[str] = None,
    ) -> IngestionResult:
        """Ingest a single file into the vector store.

        Args:
            file_path: Path to the document.
            document_id: Optional stable ID; generated if not provided.
            metadata: Additional metadata to attach to all chunks.

        Returns:
            IngestionResult with stats about the ingestion.
        """
        if document_id is None:
            document_id = str(uuid.uuid4())

        ext = file_path.suffix.lower()
        fmt = SUPPORTED_EXTENSIONS.get(ext, "unknown")

        logger.info("Ingesting %s (id=%s)", file_path.name, document_id)
        docs = self._load_document(file_path)
        chunks = self.splitter.split_documents(docs)

        base_metadata = {
            "document_id": document_id,
            "source": file_path.name,
            "format": fmt,
        }
        if metadata:
            base_metadata.update(metadata)

        for chunk in chunks:
            chunk.metadata.update(base_metadata)

        await self.retriever.add_documents(
            chunks,
            ids=[f"{document_id}_{i}" for i in range(len(chunks))],
            tenant_id=tenant_id,
        )

        logger.info(
            "Ingested %s: %d raw docs -> %d chunks", file_path.name, len(docs), len(chunks)
        )
        return IngestionResult(
            document_id=document_id,
            filename=file_path.name,
            chunks=len(chunks),
            format=fmt,
        )

    async def ingest_text(
        self,
        text: str,
        source_name: str,
        document_id: Optional[str] = None,
        metadata: Optional[dict] = None,
        tenant_id: Optional[str] = None,
    ) -> IngestionResult:
        """Ingest plain text directly into the vector store."""
        if document_id is None:
            document_id = str(uuid.uuid4())

        doc = Document(page_content=text, metadata={})
        chunks = self.splitter.split_documents([doc])

        base_metadata = {
            "document_id": document_id,
            "source": source_name,
            "format": "conversation",
        }
        if metadata:
            base_metadata.update(metadata)

        for chunk in chunks:
            chunk.metadata.update(base_metadata)

        await self.retriever.add_documents(
            chunks,
            ids=[f"{document_id}_{i}" for i in range(len(chunks))],
            tenant_id=tenant_id,
        )

        logger.info("Ingested text '%s': %d chunks", source_name, len(chunks))
        return IngestionResult(
            document_id=document_id,
            filename=source_name,
            chunks=len(chunks),
            format="conversation",
        )

    async def ingest_bytes(
        self,
        content: bytes,
        filename: str,
        document_id: Optional[str] = None,
        metadata: Optional[dict] = None,
        tenant_id: Optional[str] = None,
    ) -> IngestionResult:
        """Ingest a file from raw bytes (e.g., from an HTTP upload).

        Writes the content to a temp file, ingests it, then removes the temp file.

        Args:
            content: Raw file bytes.
            filename: Original filename (used to determine format).
            document_id: Optional stable ID.
            metadata: Additional metadata.

        Returns:
            IngestionResult with stats.
        """
        import tempfile
        import os

        suffix = Path(filename).suffix
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)

        try:
            result = await self.ingest_file(tmp_path, document_id=document_id, metadata=metadata, tenant_id=tenant_id)
            # Override filename with the original name
            result.filename = filename
            return result
        finally:
            os.unlink(tmp_path)
