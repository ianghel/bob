"""LangChain RAG pipeline combining retrieval with LLM generation."""

import logging
from typing import Optional

from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough

from core.llm.base import BaseLLMProvider, Message, MessageRole
from core.rag.retriever import ChromaRetriever

logger = logging.getLogger(__name__)

RAG_SYSTEM_PROMPT = """You are a helpful AI assistant that answers questions based on the
provided context. If the answer is not clearly found in the context, say so honestly
and provide the best answer you can from your general knowledge, clearly marking
what comes from context vs. general knowledge.

Context:
{context}
"""

RAG_HUMAN_TEMPLATE = "{question}"


class RAGResult:
    """Result from the RAG pipeline including answer and source documents."""

    def __init__(
        self,
        answer: str,
        sources: list[dict],
        query: str,
    ) -> None:
        self.answer = answer
        self.sources = sources
        self.query = query

    def to_dict(self) -> dict:
        return {
            "answer": self.answer,
            "query": self.query,
            "sources": self.sources,
        }


class RAGPipeline:
    """RAG pipeline that retrieves relevant chunks and generates an answer.

    Combines ChromaRetriever for document retrieval with an LLM provider
    for answer generation. Sources are included in every response so
    callers can cite where the answer came from.
    """

    def __init__(
        self,
        retriever: ChromaRetriever,
        llm_provider: BaseLLMProvider,
        k: int = 4,
        max_tokens: int = 2048,
        temperature: float = 0.3,
    ) -> None:
        """Initialize the RAG pipeline.

        Args:
            retriever: ChromaRetriever for document lookup.
            llm_provider: LLM provider for answer generation.
            k: Number of chunks to retrieve per query.
            max_tokens: Max tokens for the LLM response.
            temperature: LLM sampling temperature (lower = more factual).
        """
        self.retriever = retriever
        self.llm_provider = llm_provider
        self.k = k
        self.max_tokens = max_tokens
        self.temperature = temperature
        logger.info("RAGPipeline initialized (k=%d)", k)

    @staticmethod
    def _format_context(docs: list[Document]) -> str:
        """Format retrieved documents into a single context string.

        Args:
            docs: List of retrieved Document chunks.

        Returns:
            Newline-separated string of document contents with source labels.
        """
        parts = []
        for i, doc in enumerate(docs, 1):
            source = doc.metadata.get("source", "unknown")
            parts.append(f"[Source {i}: {source}]\n{doc.page_content}")
        return "\n\n".join(parts)

    @staticmethod
    def _extract_sources(docs: list[Document]) -> list[dict]:
        """Extract source metadata from retrieved documents.

        Args:
            docs: List of retrieved Document chunks.

        Returns:
            List of source metadata dicts.
        """
        seen = set()
        sources = []
        for doc in docs:
            doc_id = doc.metadata.get("document_id", "")
            source = doc.metadata.get("source", "unknown")
            key = f"{doc_id}:{source}"
            if key not in seen:
                seen.add(key)
                sources.append(
                    {
                        "document_id": doc_id,
                        "source": source,
                        "format": doc.metadata.get("format", "unknown"),
                        "excerpt": doc.page_content[:200] + "..."
                        if len(doc.page_content) > 200
                        else doc.page_content,
                    }
                )
        return sources

    async def query(
        self,
        question: str,
        session_history: Optional[list[Message]] = None,
        tenant_id: Optional[str] = None,
    ) -> RAGResult:
        """Run the full RAG pipeline for a question.

        Retrieves relevant chunks, builds a context-augmented prompt,
        calls the LLM, and returns the answer with source citations.

        Args:
            question: The user's question.
            session_history: Optional prior conversation for multi-turn RAG.

        Returns:
            RAGResult with answer, sources, and original query.
        """
        # Step 1: Retrieve relevant chunks (scoped by tenant)
        docs = await self.retriever.similarity_search(question, k=self.k, tenant_id=tenant_id)

        if not docs:
            logger.warning("No documents found for query: %r", question[:80])

        context = self._format_context(docs)
        sources = self._extract_sources(docs)

        # Step 2: Build messages for the LLM
        system_content = RAG_SYSTEM_PROMPT.format(context=context)
        messages: list[Message] = [
            Message(role=MessageRole.SYSTEM, content=system_content)
        ]

        # Include prior conversation turns if provided
        if session_history:
            messages.extend(
                [m for m in session_history if m.role != MessageRole.SYSTEM]
            )

        messages.append(Message(role=MessageRole.USER, content=question))

        # Step 3: Generate the answer
        response = await self.llm_provider.chat(
            messages=messages,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
        )

        logger.info(
            "RAG query answered: %d chunks retrieved, %d sources cited",
            len(docs),
            len(sources),
        )

        return RAGResult(
            answer=response.content,
            sources=sources,
            query=question,
        )
