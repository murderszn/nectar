"""
Shared data models for chat messages, tool calls, and registry metadata.

Kept free of I/O so they can be unit-tested in isolation.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Callable, Optional


class Role(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass
class ToolCallFunction:
    name: str
    arguments: str  # raw JSON string from the model

    def parsed_args(self) -> dict[str, Any]:
        """Parse tool arguments; tolerate empty / non-object payloads."""
        if not self.arguments or not self.arguments.strip():
            return {}
        try:
            data = json.loads(self.arguments)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid tool arguments JSON for {self.name}: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError(f"Tool arguments must be a JSON object, got {type(data).__name__}")
        return data


@dataclass
class ToolCall:
    """One tool invocation requested by the model (OpenAI shape)."""

    id: str
    type: str  # always "function" for now
    function: ToolCallFunction


@dataclass
class Message:
    """Chat message compatible with OpenAI chat.completions."""

    role: str
    content: Optional[str] = None
    tool_calls: Optional[list[ToolCall]] = None
    tool_call_id: Optional[str] = None
    name: Optional[str] = None

    def to_api_dict(self) -> dict[str, Any]:
        """Serialize to the wire format expected by OpenAI-compatible APIs."""
        payload: dict[str, Any] = {"role": self.role}
        if self.content is not None:
            payload["content"] = self.content
        if self.tool_calls:
            payload["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": tc.type,
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in self.tool_calls
            ]
        if self.tool_call_id is not None:
            payload["tool_call_id"] = self.tool_call_id
        if self.name is not None:
            payload["name"] = self.name
        return payload


@dataclass
class ChatChoice:
    message: Message
    finish_reason: Optional[str] = None


@dataclass
class ChatCompletion:
    """Normalized non-streaming completion response."""

    id: str
    model: str
    choices: list[ChatChoice]
    usage: dict[str, Any] = field(default_factory=dict)

    @property
    def first_message(self) -> Message:
        if not self.choices:
            raise RuntimeError("Completion contained no choices")
        return self.choices[0].message


# ---------------------------------------------------------------------------
# Tool registry descriptors
# ---------------------------------------------------------------------------

ToolHandler = Callable[..., str]


@dataclass
class ToolParameter:
    name: str
    type: str
    description: str
    required: bool = True


@dataclass
class ToolSpec:
    """
    Self-describing tool: JSON schema for the model + Python handler.

    `handler` receives keyword arguments matching parameter names and
    must return a string (stdout / result body) for the tool message.
    """

    name: str
    description: str
    parameters: list[ToolParameter]
    handler: ToolHandler

    def openai_schema(self) -> dict[str, Any]:
        """OpenAI `tools[]` function schema entry."""
        props: dict[str, Any] = {}
        required: list[str] = []
        for p in self.parameters:
            props[p.name] = {"type": p.type, "description": p.description}
            if p.required:
                required.append(p.name)
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": props,
                    "required": required,
                },
            },
        }

    def invoke(self, **kwargs: Any) -> str:
        return self.handler(**kwargs)


def message_from_api(data: dict[str, Any]) -> Message:
    """Parse an assistant/user/tool message dict from the API."""
    tool_calls_raw = data.get("tool_calls") or None
    tool_calls: Optional[list[ToolCall]] = None
    if tool_calls_raw:
        tool_calls = []
        for tc in tool_calls_raw:
            fn = tc.get("function") or {}
            tool_calls.append(
                ToolCall(
                    id=str(tc.get("id") or ""),
                    type=str(tc.get("type") or "function"),
                    function=ToolCallFunction(
                        name=str(fn.get("name") or ""),
                        arguments=fn.get("arguments")
                        if isinstance(fn.get("arguments"), str)
                        else json.dumps(fn.get("arguments") or {}),
                    ),
                )
            )
    content = data.get("content")
    # Some providers return null content when only tool_calls are present
    if content is not None and not isinstance(content, str):
        content = json.dumps(content)
    return Message(
        role=str(data.get("role") or "assistant"),
        content=content,
        tool_calls=tool_calls,
        tool_call_id=data.get("tool_call_id"),
        name=data.get("name"),
    )


def as_debug_dict(obj: Any) -> Any:
    """Best-effort dataclass → dict for logging."""
    try:
        return asdict(obj)
    except TypeError:
        return str(obj)
