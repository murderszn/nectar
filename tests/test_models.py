"""Message serialization."""

from opencode_harness.models import Message, ToolCall, ToolCallFunction, message_from_api


def test_tool_message_roundtrip():
    m = Message(role="tool", content="ok", tool_call_id="call_1", name="execute_bash_command")
    d = m.to_api_dict()
    assert d["role"] == "tool"
    assert d["tool_call_id"] == "call_1"
    assert d["content"] == "ok"


def test_assistant_with_tool_calls():
    raw = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "c1",
                "type": "function",
                "function": {"name": "view_workspace_file", "arguments": '{"path": "a.py"}'},
            }
        ],
    }
    msg = message_from_api(raw)
    assert msg.tool_calls is not None
    assert msg.tool_calls[0].function.name == "view_workspace_file"
    assert msg.tool_calls[0].function.parsed_args()["path"] == "a.py"


def test_parsed_args_empty():
    fn = ToolCallFunction(name="x", arguments="")
    assert fn.parsed_args() == {}
