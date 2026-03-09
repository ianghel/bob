"""Abstract base class for LLM providers."""

from abc import ABC, abstractmethod
from enum import Enum
from typing import AsyncIterator, Optional
from pydantic import BaseModel


class MessageRole(str, Enum):
    """Roles for conversation messages."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class Message(BaseModel):
    """A single conversation message."""

    role: MessageRole
    content: str


class LLMResponse(BaseModel):
    """Response from an LLM provider."""

    content: str
    model: str
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    stop_reason: Optional[str] = None


class BaseLLMProvider(ABC):
    """Abstract base class for all LLM providers.

    Defines the common interface that all providers must implement,
    enabling seamless switching between Bedrock and local models.
    """

    @abstractmethod
    async def chat(
        self,
        messages: list[Message],
        max_tokens: int = 4096,
        temperature: float = 0.7,
        system_prompt: Optional[str] = None,
    ) -> LLMResponse:
        """Send a chat request and return a complete response.

        Args:
            messages: Conversation history as a list of messages.
            max_tokens: Maximum tokens to generate.
            temperature: Sampling temperature (0.0-1.0).
            system_prompt: Optional system prompt to override default.

        Returns:
            LLMResponse with generated content and metadata.
        """
        ...

    @abstractmethod
    async def stream(
        self,
        messages: list[Message],
        max_tokens: int = 4096,
        temperature: float = 0.7,
        system_prompt: Optional[str] = None,
    ) -> AsyncIterator[str]:
        """Stream a chat response token by token.

        Args:
            messages: Conversation history as a list of messages.
            max_tokens: Maximum tokens to generate.
            temperature: Sampling temperature (0.0-1.0).
            system_prompt: Optional system prompt to override default.

        Yields:
            String chunks as they are generated.
        """
        ...

    @abstractmethod
    async def embed(self, text: str) -> list[float]:
        """Generate an embedding vector for a text.

        Args:
            text: The input text to embed.

        Returns:
            A list of floats representing the embedding vector.
        """
        ...
