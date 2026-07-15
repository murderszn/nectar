"""OpenCode/Hermes-style coding tool tests."""

from pathlib import Path

from opencode_harness.config import ToolConfig
from opencode_harness.tools.registry import ToolRegistry


def _reg(tmp: Path, mode: str = "build") -> ToolRegistry:
    return ToolRegistry(
        tmp,
        ToolConfig(),
        confirm_destructive=lambda c, r: False,
        mode=mode,  # type: ignore[arg-type]
    )


def test_read_file_line_numbers(tmp_path: Path):
    (tmp_path / "a.py").write_text("one\ntwo\nthree\n", encoding="utf-8")
    reg = _reg(tmp_path)
    out = reg.dispatch("read_file", {"path": "a.py", "offset": 2, "limit": 1})
    assert "2|" in out
    assert "two" in out
    assert "one" not in out.split("---", 1)[-1]


def test_edit_file_unique(tmp_path: Path):
    (tmp_path / "b.py").write_text("def hello():\n    return 1\n", encoding="utf-8")
    reg = _reg(tmp_path)
    out = reg.dispatch(
        "edit_file",
        {
            "path": "b.py",
            "old_string": "return 1",
            "new_string": "return 2",
        },
    )
    assert out.startswith("OK:")
    assert "return 2" in (tmp_path / "b.py").read_text(encoding="utf-8")


def test_edit_file_ambiguous(tmp_path: Path):
    (tmp_path / "c.py").write_text("x = 1\nx = 1\n", encoding="utf-8")
    reg = _reg(tmp_path)
    out = reg.dispatch(
        "edit_file",
        {"path": "c.py", "old_string": "x = 1", "new_string": "x = 2"},
    )
    assert out.startswith("ERROR:")
    assert "2 times" in out


def test_glob_and_grep(tmp_path: Path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "mod.py").write_text("def find_me():\n    pass\n", encoding="utf-8")
    reg = _reg(tmp_path)
    g = reg.dispatch("glob_files", {"pattern": "**/*.py"})
    assert "mod.py" in g
    s = reg.dispatch("grep_search", {"pattern": "find_me", "glob": "*.py"})
    assert "find_me" in s


def test_list_directory(tmp_path: Path):
    (tmp_path / "hello.txt").write_text("hi", encoding="utf-8")
    reg = _reg(tmp_path)
    out = reg.dispatch("list_directory", {"path": "."})
    assert "hello.txt" in out


def test_plan_mode_no_write(tmp_path: Path):
    reg = _reg(tmp_path, mode="plan")
    names = set(reg.list_names())
    assert "read_file" in names
    assert "grep_search" in names
    assert "write_file" not in names
    assert "edit_file" not in names
    assert "execute_bash_command" not in names


def test_core_tools_present(tmp_path: Path):
    reg = _reg(tmp_path)
    names = set(reg.list_names())
    for required in {
        "read_file",
        "write_file",
        "edit_file",
        "glob_files",
        "grep_search",
        "list_directory",
        "execute_bash_command",
        "browse_web_content",
    }:
        assert required in names
