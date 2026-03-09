"""Local model provider via OpenAI-compatible API."""

import logging
from typing import AsyncIterator, Optional

from openai import AsyncOpenAI

from core.llm.base import BaseLLMProvider, LLMResponse, Message, MessageRole

logger = logging.getLogger(__name__)


class LocalProvider(BaseLLMProvider):
    """Local model provider using an OpenAI-compatible endpoint.

    Works with any OpenAI-compatible inference server
    (LM Studio, Ollama, vLLM, etc.).

    For embeddings, falls back to sentence-transformers when
    a dedicated embedding endpoint is not available.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:1234/v1",
        model_name: str = "your-model-name",
        api_key: str = "not-needed",
        embed_model_name: str = "text-embedding-nomic-embed-text-v1.5",
        st_fallback_model: str = "all-MiniLM-L6-v2",
    ) -> None:
        """Initialize the local provider.

        Args:
            base_url: Base URL for the OpenAI-compatible inference server.
            model_name: Chat model identifier as expected by the server.
            api_key: API key for the server.
            embed_model_name: Embedding model ID on the server (uses /v1/embeddings).
                Set to empty string to force the sentence-transformers fallback.
            st_fallback_model: sentence-transformers model used when the server
                does not expose an embeddings endpoint.
        """
        self.model_name = model_name
        self.embed_model_name = embed_model_name
        self.st_fallback_model = st_fallback_model
        self._client = AsyncOpenAI(
            base_url=base_url,
            api_key=api_key,
            default_headers={"User-Agent": "curl/7.88.1"},
        )
        self._st_model = None  # Lazy-loaded only if server embed fails
        logger.info("LocalProvider initialized pointing to %s model=%s", base_url, model_name)

    def _build_openai_messages(
        self,
        messages: list[Message],
        system_prompt: Optional[str],
    ) -> list[dict]:
        """Convert internal Message list to OpenAI chat format.

        Args:
            messages: Internal message list.
            system_prompt: Override or prepend system prompt.

        Returns:
            List of dicts in OpenAI message format.
        """
        openai_messages: list[dict] = []

        # Prepend system prompt if provided
        system_msgs = [m.content for m in messages if m.role == MessageRole.SYSTEM]
        effective_system = system_prompt or (system_msgs[0] if system_msgs else None)
        if effective_system:
            openai_messages.append({"role": "system", "content": effective_system})

        for msg in messages:
            if msg.role != MessageRole.SYSTEM:
                openai_messages.append({"role": msg.role.value, "content": msg.content})

        return openai_messages

    async def chat(
        self,
        messages: list[Message],
        max_tokens: int = 4096,
        temperature: float = 0.7,
        system_prompt: Optional[str] = None,
    ) -> LLMResponse:
        """Send a chat request to the local model and return a complete response."""
        openai_messages = self._build_openai_messages(messages, system_prompt)
        try:
            response = await self._client.chat.completions.create(
                model=self.model_name,
                messages=openai_messages,
                max_tokens=max_tokens,
                temperature=temperature,
                stream=False,
            )
            choice = response.choices[0]
            usage = response.usage
            return LLMResponse(
                content=choice.message.content or "",
                model=self.model_name,
                input_tokens=usage.prompt_tokens if usage else None,
                output_tokens=usage.completion_tokens if usage else None,
                stop_reason=choice.finish_reason,
            )
        except Exception as e:
            logger.error("LocalProvider chat error: %s", e)
            raise

    async def stream(
        self,
        messages: list[Message],
        max_tokens: int = 4096,
        temperature: float = 0.7,
        system_prompt: Optional[str] = None,
    ) -> AsyncIterator[str]:
        """Stream a chat response from the local model token by token."""
        openai_messages = self._build_openai_messages(messages, system_prompt)
        try:
            async with await self._client.chat.completions.create(
                model=self.model_name,
                messages=openai_messages,
                max_tokens=max_tokens,
                temperature=temperature,
                stream=True,
            ) as stream:
                async for chunk in stream:
                    delta = chunk.choices[0].delta
                    if delta.content:
                        yield delta.content
        except Exception as e:
            logger.error("LocalProvider stream error: %s", e)
            raise

    async def embed(self, text: str) -> list[float]:
        """Generate an embedding vector for the given text.

        Tries the server's native /v1/embeddings endpoint first (faster, no local
        model download). Falls back to sentence-transformers if the server model
        name is empty or the request fails.

        Args:
            text: Input text to embed.

        Returns:
            Embedding vector as a list of floats.
        """
        if self.embed_model_name:
            try:
                response = await self._client.embeddings.create(
                    model=self.embed_model_name,
                    input=text,
                )
                return response.data[0].embedding
            except Exception as e:
                logger.warning(
                    "Server embedding failed (%s), falling back to sentence-transformers", e
                )

        # Sentence-transformers fallback
        if self._st_model is None:
            try:
                from sentence_transformers import SentenceTransformer

                self._st_model = SentenceTransformer(self.st_fallback_model)
                logger.info("Loaded sentence-transformers fallback: %s", self.st_fallback_model)
            except ImportError:
                raise ImportError(
                    "sentence-transformers is required when no server embedding model is set. "
                    "Install with: pip install sentence-transformers"
                )
        vector = self._st_model.encode(text, normalize_embeddings=True)
        return vector.tolist()
