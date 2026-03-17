"""Amazon Bedrock LLM provider implementation."""

import asyncio
import json
import logging
from typing import AsyncIterator, Optional

import boto3
from botocore.exceptions import ClientError

from core.llm.base import BaseLLMProvider, LLMResponse, Message, MessageRole

logger = logging.getLogger(__name__)

CHAT_MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
EMBED_MODEL_ID = "amazon.titan-embed-text-v2:0"


class BedrockProvider(BaseLLMProvider):
    """Amazon Bedrock LLM provider.

    Uses boto3 to call Bedrock runtime for both chat inference
    and text embeddings. Supports streaming and tool calling via
    the Converse API.
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

    @staticmethod
    def _openai_tools_to_bedrock(tools: list[dict]) -> list[dict]:
        """Convert OpenAI function-calling tool schemas to Bedrock toolConfig format.

        Args:
            tools: List of OpenAI-style tool dicts with type/function keys.

        Returns:
            List of Bedrock toolSpec dicts.
        """
        bedrock_tools = []
        for tool in tools:
            fn = tool.get("function", tool)
            bedrock_tools.append({
                "toolSpec": {
                    "name": fn["name"],
                    "description": fn.get("description", ""),
                    "inputSchema": {
                        "json": fn.get("parameters", {"type": "object", "properties": {}})
                    },
                }
            })
        return bedrock_tools

    async def chat_with_tools(
        self,
        messages: list[Message],
        tools: list[dict],
        tool_executor,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        system_prompt: Optional[str] = None,
        max_rounds: int = 5,
    ) -> LLMResponse:
        """Chat with Bedrock Converse API tool use.

        Sends messages + tool definitions to Claude. When the model responds
        with tool_use blocks, executes them via ``tool_executor`` and feeds
        the results back until the model produces a final text response.

        Args:
            messages: Conversation history.
            tools: OpenAI function-calling tool schemas (auto-converted to Bedrock format).
            tool_executor: ``(name: str, arguments: str|dict) -> str`` callable.
            max_tokens: Max tokens per LLM call.
            temperature: Sampling temperature.
            system_prompt: Optional system prompt override.
            max_rounds: Safety cap on tool-call round-trips.

        Returns:
            LLMResponse with final content and tools_used metadata.
        """
        # Build initial Bedrock messages from internal format
        converse_messages = [
            {"role": msg.role.value, "content": [{"text": msg.content}]}
            for msg in messages
            if msg.role != MessageRole.SYSTEM
        ]

        # System prompt
        system_msgs = [m.content for m in messages if m.role == MessageRole.SYSTEM]
        effective_system = system_prompt or (system_msgs[0] if system_msgs else None)
        system_block = [{"text": effective_system}] if effective_system else None

        # Convert tool schemas
        bedrock_tools = self._openai_tools_to_bedrock(tools)
        tool_config = {"tools": bedrock_tools}

        tools_used: list[dict] = []

        for _ in range(max_rounds):
            try:
                kwargs: dict = {
                    "modelId": self.chat_model_id,
                    "messages": converse_messages,
                    "inferenceConfig": {
                        "maxTokens": max_tokens,
                        "temperature": temperature,
                    },
                    "toolConfig": tool_config,
                }
                if system_block:
                    kwargs["system"] = system_block

                response = self._client.converse(**kwargs)
            except ClientError as e:
                logger.error("Bedrock chat_with_tools error: %s", e)
                raise

            output_msg = response["output"]["message"]
            stop_reason = response.get("stopReason", "")

            # Check if model wants to use tools
            if stop_reason == "tool_use":
                # Append assistant message (contains toolUse blocks)
                converse_messages.append(output_msg)

                # Process each tool use block
                tool_results = []
                for block in output_msg["content"]:
                    if "toolUse" in block:
                        tu = block["toolUse"]
                        fn_name = tu["name"]
                        fn_args = tu["input"]
                        tool_use_id = tu["toolUseId"]

                        logger.info("Bedrock tool call: %s(%s)", fn_name, str(fn_args)[:200])

                        # Execute tool (support both sync and async executors)
                        result = tool_executor(fn_name, fn_args)
                        if asyncio.iscoroutine(result):
                            result = await result

                        tools_used.append({
                            "name": fn_name,
                            "arguments": fn_args,
                            "result_preview": str(result)[:200],
                        })

                        tool_results.append({
                            "toolResult": {
                                "toolUseId": tool_use_id,
                                "content": [{"text": str(result)}],
                            }
                        })

                # Send tool results back
                converse_messages.append({
                    "role": "user",
                    "content": tool_results,
                })
            else:
                # Final text response
                content = ""
                for block in output_msg["content"]:
                    if "text" in block:
                        content += block["text"]

                usage = response.get("usage", {})
                return LLMResponse(
                    content=content,
                    model=self.chat_model_id,
                    input_tokens=usage.get("inputTokens"),
                    output_tokens=usage.get("outputTokens"),
                    stop_reason=stop_reason,
                    tools_used=tools_used or None,
                )

        # Exhausted rounds
        logger.warning("Bedrock chat_with_tools hit max_rounds=%d", max_rounds)
        return LLMResponse(
            content="I was unable to complete the task within the allowed number of steps.",
            model=self.chat_model_id,
            tools_used=tools_used or None,
        )

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
