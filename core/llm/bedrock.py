"""Amazon Bedrock LLM provider implementation."""

import json
import logging
from typing import AsyncIterator, Optional

import boto3
from botocore.exceptions import ClientError

from core.llm.base import BaseLLMProvider, LLMResponse, Message, MessageRole

logger = logging.getLogger(__name__)

CHAT_MODEL_ID = "anthropic.claude-3-5-sonnet-20241022-v2:0"
EMBED_MODEL_ID = "amazon.titan-embed-text-v2:0"


class BedrockProvider(BaseLLMProvider):
    """Amazon Bedrock LLM provider.

    Uses boto3 to call Bedrock runtime for both chat inference
    and text embeddings. Supports streaming via invoke_model_with_response_stream.
    """

    def __init__(
        self,
        region: str = "us-east-1",
        chat_model_id: str = CHAT_MODEL_ID,
        embed_model_id: str = EMBED_MODEL_ID,
    ) -> None:
        """Initialize the Bedrock provider.

        Args:
            region: AWS region for Bedrock runtime.
            chat_model_id: Model ID for chat/inference calls.
            embed_model_id: Model ID for embedding calls.
        """
        self.chat_model_id = chat_model_id
        self.embed_model_id = embed_model_id
        self._client = boto3.client("bedrock-runtime", region_name=region)
        logger.info("BedrockProvider initialized with model %s", chat_model_id)

    def _build_request_body(
        self,
        messages: list[Message],
        max_tokens: int,
        temperature: float,
        system_prompt: Optional[str],
    ) -> dict:
        """Build the Bedrock Converse API request body.

        Args:
            messages: Conversation messages (system messages excluded).
            max_tokens: Max tokens cap.
            temperature: Sampling temperature.
            system_prompt: Optional system string.

        Returns:
            Dict suitable for json-serialization and Bedrock invocation.
        """
        converse_messages = [
            {"role": msg.role.value, "content": [{"text": msg.content}]}
            for msg in messages
            if msg.role != MessageRole.SYSTEM
        ]

        body: dict = {
            "messages": converse_messages,
            "inferenceConfig": {
                "maxTokens": max_tokens,
                "temperature": temperature,
            },
        }

        # Extract system messages or use explicit system_prompt
        system_msgs = [m.content for m in messages if m.role == MessageRole.SYSTEM]
        effective_system = system_prompt or (system_msgs[0] if system_msgs else None)
        if effective_system:
            body["system"] = [{"text": effective_system}]

        return body

    async def chat(
        self,
        messages: list[Message],
        max_tokens: int = 4096,
        temperature: float = 0.7,
        system_prompt: Optional[str] = None,
    ) -> LLMResponse:
        """Send a chat request to Bedrock and return a complete response."""
        body = self._build_request_body(messages, max_tokens, temperature, system_prompt)
        try:
            response = self._client.converse(
                modelId=self.chat_model_id,
                **body,
            )
            output_message = response["output"]["message"]
            content = output_message["content"][0]["text"]
            usage = response.get("usage", {})
            return LLMResponse(
                content=content,
                model=self.chat_model_id,
                input_tokens=usage.get("inputTokens"),
                output_tokens=usage.get("outputTokens"),
                stop_reason=response.get("stopReason"),
            )
        except ClientError as e:
            logger.error("Bedrock chat error: %s", e)
            raise

    async def stream(
        self,
        messages: list[Message],
        max_tokens: int = 4096,
        temperature: float = 0.7,
        system_prompt: Optional[str] = None,
    ) -> AsyncIterator[str]:
        """Stream a chat response from Bedrock token by token."""
        body = self._build_request_body(messages, max_tokens, temperature, system_prompt)
        try:
            response = self._client.converse_stream(
                modelId=self.chat_model_id,
                **body,
            )
            for event in response["stream"]:
                if "contentBlockDelta" in event:
                    delta = event["contentBlockDelta"].get("delta", {})
                    if "text" in delta:
                        yield delta["text"]
        except ClientError as e:
            logger.error("Bedrock stream error: %s", e)
            raise

    async def embed(self, text: str) -> list[float]:
        """Generate an embedding using Amazon Titan Embed."""
        body = json.dumps({"inputText": text})
        try:
            response = self._client.invoke_model(
                modelId=self.embed_model_id,
                body=body,
                contentType="application/json",
                accept="application/json",
            )
            result = json.loads(response["body"].read())
            return result["embedding"]
        except ClientError as e:
            logger.error("Bedrock embed error: %s", e)
            raise
