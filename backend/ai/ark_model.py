from __future__ import annotations

import json
from typing import Any, TypeVar

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolCall, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import BaseModel, Field
from volcenginesdkarkruntime import Ark

import config
from schemas.llm_schemas import LangChainRole

T = TypeVar("T", bound=BaseModel)


class ArkChatModel(BaseChatModel):
    client: Any | None = Field(default=None, exclude=True)
    thinking: dict[str, Any] | None = Field(default=None)

    @property
    def _llm_type(self) -> str:
        return "ark-chat"

    @property
    def _identifying_params(self) -> dict[str, Any]:
        return {
            "model": config.DOUBAO_CHAT_MODEL,
            "base_url": config.DOUBAO_BASE_URL,
        }

    def _get_client(self) -> Ark:
        return self.client or Ark(api_key=config.DOUBAO_API_KEY, base_url=config.DOUBAO_BASE_URL)

    def bind_tools(self, tools: list, **kwargs: Any) -> Any:
        formatted = [convert_to_openai_tool(t) for t in tools]
        return self.bind(tools=formatted, **kwargs)

    def parse(self, messages: list[dict], response_format: type[T], thinking_disabled: bool = True) -> T | None:
        """Call beta structured parsing and return the parsed model, or None on empty response."""
        client = self._get_client()
        extra_body: dict[str, Any] = {"thinking": {"type": "disabled"}} if thinking_disabled else {}
        completion = client.beta.chat.completions.parse(
            model=config.DOUBAO_CHAT_MODEL,
            messages=messages,
            response_format=response_format,
            extra_body=extra_body or None,
        )
        return completion.choices[0].message.parsed

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        client = self._get_client()
        request_kwargs: dict[str, Any] = {
            "model": config.DOUBAO_CHAT_MODEL,
            "messages": [self._to_ark_message(message) for message in messages],
            "stop": stop,
        }
        if self.thinking is not None and "thinking" not in kwargs:
            request_kwargs["thinking"] = self.thinking
        request_kwargs.update(kwargs)
        response = client.chat.completions.create(**request_kwargs)
        content = self._coerce_content(response.choices[0].message.content)
        
        # Parse tool calls from response
        tool_calls = []
        if hasattr(response.choices[0].message, 'tool_calls') and response.choices[0].message.tool_calls:
            for tc in response.choices[0].message.tool_calls:
                tool_calls.append(
                    ToolCall(
                        name=tc.function.name,
                        args=json.loads(tc.function.arguments),
                        id=tc.id,
                    )
                )
        
        message = AIMessage(
            content=content,
            tool_calls=tool_calls,
        )
        generation = ChatGeneration(message=message)
        return ChatResult(generations=[generation])

    def _to_ark_message(self, message: BaseMessage) -> dict[str, Any]:
        # ToolMessage requires tool_call_id and name fields
        if isinstance(message, ToolMessage):
            return {
                "role": "tool",
                "content": self._coerce_content(message.content),
                "tool_call_id": message.tool_call_id,
                "name": message.name,
            }

        # AIMessage with tool_calls must include tool_calls field
        if isinstance(message, AIMessage) and message.tool_calls:
            return {
                "role": "assistant",
                "content": self._coerce_content(message.content),
                "tool_calls": [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": json.dumps(tc["args"]),
                        },
                    }
                    for tc in message.tool_calls
                ],
            }

        try:
            langchain_role = LangChainRole(message.type)
        except ValueError as exc:
            raise ValueError(f"Unsupported LangChain message type: {message.type}") from exc
        role = langchain_role.to_model_role()

        return {
            "role": role,
            "content": self._coerce_content(message.content),
        }

    def _coerce_content(self, content: Any) -> str:
        # LangChain message content is not always a plain string.
        # Normalize common content shapes into a single text string before:
        # 1. sending messages to Ark, which expects {"content": "..."} in this wrapper
        # 2. creating AIMessage(content=...) on the way back to LangChain
        #
        # Examples:
        # - "hello" -> "hello"
        # - [{"text": "hello"}, {"text": " world"}] -> "hello world"
        # - ["hello", " world"] -> "hello world"
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict) and "text" in item:
                    parts.append(str(item["text"]))
                else:
                    parts.append(str(item))
            return "".join(parts)
        return str(content)
