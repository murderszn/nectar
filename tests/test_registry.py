"""ToolRegistry dispatch and file tools."""

from pathlib import Path

from opencode_harness.config import ToolConfig
from opencode_harness.tools.registry import ToolRegistry


def test_write_and_view_roundtrip(tmp_path: Path):
    reg = ToolRegistry(tmp_path, ToolConfig(), confirm_destructive=lambda c, r: False)
    out = reg.dispatch(
        "write_workspace_file",
        {"path": "hello.py", "content": "print('hi')\n"},
    )
    assert out.startswith("OK:")
    viewed = reg.dispatch("view_workspace_file", {"path": "hello.py"})
    assert "print('hi')" in viewed


def test_unknown_tool():
    reg = ToolRegistry(Path("."), ToolConfig())
    result = reg.dispatch("not_a_tool", {})
    assert result.startswith("ERROR: unknown tool")


def test_bash_echo(tmp_path: Path):
    reg = ToolRegistry(tmp_path, ToolConfig(), confirm_destructive=lambda c, r: False)
    result = reg.dispatch("execute_bash_command", {"command": "echo hello-harness"})
    assert "hello-harness" in result
    assert "exit_code: 0" in result


def test_destructive_bash_denied(tmp_path: Path):
    reg = ToolRegistry(tmp_path, ToolConfig(), confirm_destructive=lambda c, r: False)
    result = reg.dispatch("execute_bash_command", {"command": "rm -rf nowhere"})
    assert result.startswith("BLOCKED:")


def test_openai_schemas_present(tmp_path: Path):
    reg = ToolRegistry(tmp_path, ToolConfig())
    schemas = reg.openai_tools()
    names = {s["function"]["name"] for s in schemas}
    # Core OpenCode/Hermes-style coding tools (+ legacy aliases)
    for required in {
        "execute_bash_command",
        "read_file",
        "write_file",
        "edit_file",
        "glob_files",
        "grep_search",
        "list_directory",
        "browse_web_content",
        "view_workspace_file",
        "write_workspace_file",
    }:
        assert required in names
