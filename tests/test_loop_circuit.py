"""Agent loop circuit breaker with a fake client."""

from pathlib import Path
from typing import Any, Optional
from unittest.mock import MagicMock

from opencode_harness.agent.loop import AgentLoop
from opencode_harness.config import AppConfig, ToolConfig
from opencode_harness.models import ChatChoice, ChatCompletion, Message, ToolCall, ToolCallFunction
from opencode_harness.tools.registry import ToolRegistry


def _tool_response(call_id: str = "c1") -> ChatCompletion:
    return ChatCompletion(
        id="x",
        model="test",
        choices=[
            ChatChoice(
                message=Message(
                    role="assistant",
                    content=None,
                    tool_calls=[
                        ToolCall(
                            id=call_id,
                            type="function",
                            function=ToolCallFunction(
                                name="execute_bash_command",
                                arguments='{"command": "echo loop"}',
                            ),
                        )
                    ],
                ),
                finish_reason="tool_calls",
            )
        ],
    )


def test_circuit_breaker(tmp_path: Path):
    config = AppConfig(workspace=tmp_path, tools=ToolConfig(max_tool_rounds=3))
    registry = ToolRegistry(tmp_path, config.tools, confirm_destructive=lambda c, r: False)

    client = MagicMock()
    # Always request another tool call
    client.chat.return_value = _tool_response()

    loop = AgentLoop(config, client, registry)
    result = loop.run("keep going forever")

    assert result.stopped_reason == "circuit_breaker"
    assert result.tool_rounds == 3
    assert client.chat.call_count >= 1
