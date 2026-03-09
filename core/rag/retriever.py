"""ChromaDB vector retriever for the RAG pipeline with tenant isolation."""

import logging
from typing import Optional

import chromadb
from chromadb.config import Settings
from langchain_chroma import Chroma
from langchain_core.documents import Document

logger = logging.getLogger(__name__)

COLLECTION_NAME = "knowledge_base"


class ChromaRetriever:
    """Wraps ChromaDB for document storage and similarity search.

    Supports tenant isolation via tenant_id metadata filtering.
    All documents are stored in a single collection with tenant_id
    metadata for row-level isolation.
    """

    def __init__(
        self,
        embedding_function,
        host: str = "localhost",
        port: int = 8001,
        persist_directory: str = "./data/chroma_db",
        use_http_client: bool = False,
    ) -> None:
        self.embedding_function = embedding_function

        if use_http_client:
            self._chroma_client = chromadb.HttpClient(
                host=host,
                port=port,
                settings=Settings(anonymized_telemetry=False),
            )
            logger.info("ChromaRetriever connected to remote %s:%d", host, port)
        else:
            self._chroma_client = chromadb.PersistentClient(
                path=persist_directory,
                settings=Settings(anonymized_telemetry=False),
            )
            logger.info("ChromaRetriever using persistent store at %s", persist_directory)

        self._vectorstore = Chroma(
            client=self._chroma_client,
            collection_name=COLLECTION_NAME,
            embedding_function=embedding_function,
        )

    async def add_documents(
        self,
        documents: list[Document],
        ids: Optional[list[str]] = None,
        tenant_id: Optional[str] = None,
    ) -> None:
        """Add pre-chunked documents to the vector store.

        If tenant_id is provided, it is injected into each document's metadata.
        """
        if not documents:
            return
        if tenant_id:
            for doc in documents:
                doc.metadata["tenant_id"] = tenant_id
        self._vectorstore.add_documents(documents=documents, ids=ids)
        logger.debug("Added %d chunks to vector store (tenant=%s)", len(documents), tenant_id)

    async def similarity_search(
        self,
        query: str,
        k: int = 4,
        filter: Optional[dict] = None,
        tenant_id: Optional[str] = None,
    ) -> list[Document]:
        """Retrieve the top-k most relevant documents for a query.

        If tenant_id is provided, results are filtered to that tenant.
        """
        search_filter = dict(filter) if filter else {}
        if tenant_id:
            search_filter["tenant_id"] = tenant_id

        docs = self._vectorstore.similarity_search(
            query=query, k=k, filter=search_filter or None
        )
        logger.debug("Similarity search for %r returned %d docs", query[:50], len(docs))
        return docs

    async def similarity_search_with_score(
        self,
        query: str,
        k: int = 4,
        tenant_id: Optional[str] = None,
    ) -> list[tuple[Document, float]]:
        """Retrieve documents with relevance scores, scoped by tenant."""
        search_filter = {"tenant_id": tenant_id} if tenant_id else None
        return self._vectorstore.similarity_search_with_relevance_scores(
            query=query, k=k, filter=search_filter
        )

    def list_documents(self, tenant_id: Optional[str] = None) -> list[dict]:
        """List all unique source documents, optionally filtered by tenant."""
        collection = self._chroma_client.get_collection(COLLECTION_NAME)

        get_kwargs = {"include": ["metadatas"]}
        if tenant_id:
            get_kwargs["where"] = {"tenant_id": tenant_id}

        result = collection.get(**get_kwargs)
        metadatas = result.get("metadatas") or []

        docs: dict[str, dict] = {}
        for meta in metadatas:
            doc_id = meta.get("document_id", "unknown")
            if doc_id not in docs:
                docs[doc_id] = {
                    "document_id": doc_id,
                    "source": meta.get("source", "unknown"),
                    "format": meta.get("format", "unknown"),
                    "chunk_count": 0,
                }
            docs[doc_id]["chunk_count"] += 1

        return list(docs.values())

    def delete_document(self, document_id: str, tenant_id: Optional[str] = None) -> int:
        """Delete all chunks belonging to a document, scoped by tenant."""
        collection = self._chroma_client.get_collection(COLLECTION_NAME)

        where_filter = {"document_id": document_id}
        if tenant_id:
            where_filter = {"$and": [{"document_id": document_id}, {"tenant_id": tenant_id}]}

        result = collection.get(where=where_filter)
        ids_to_delete = result.get("ids") or []
        if ids_to_delete:
            collection.delete(ids=ids_to_delete)
        logger.info("Deleted %d chunks for document_id=%s (tenant=%s)", len(ids_to_delete), document_id, tenant_id)
        return len(ids_to_delete)

    def as_langchain_retriever(self, k: int = 4):
        """Return a LangChain-compatible retriever object."""
        return self._vectorstore.as_retriever(search_kwargs={"k": k})
