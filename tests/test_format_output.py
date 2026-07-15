"""Structured assistant output formatting tests."""

from rich.console import Console

from opencode_harness.ui.format_output import (
    print_assistant_output,
    render_assistant_output,
    segment_output,
)


def test_fenced_code_segment():
    text = "Here is code:\n\n```python\ndef hi():\n    print('x')\n```\n\nDone."
    segs = segment_output(text)
    kinds = [s.kind for s in segs]
    assert "code" in kinds
    assert "prose" in kinds
    code = next(s for s in segs if s.kind == "code")
    assert "def hi" in code.text
    assert code.language == "python"


def test_ascii_art_unfenced():
    art = "\n".join(
        [
            "    +---+",
            "    | A |",
            "    +---+",
            "      |",
            "    +---+",
            "    | B |",
            "    +---+",
        ]
    )
    text = f"Diagram:\n\n{art}\n\nThat's the flow."
    segs = segment_output(text)
    assert any(s.kind == "pre" for s in segs)


def test_markdown_table():
    text = """\
Results:

| Model | Score |
|-------|------:|
| kimi  |  98   |
| hermes|  91   |

Nice.
"""
    segs = segment_output(text)
    assert any(s.kind == "table" for s in segs)


def test_bar_chart_block():
    chart = "\n".join(
        [
            "sales  ████████░░  80",
            "cost   ████░░░░░░  40",
            "profit ██████░░░░  60",
        ]
    )
    segs = segment_output(chart)
    assert any(s.kind == "pre" for s in segs)


def test_render_prints_without_error():
    console = Console(record=True, width=80, force_terminal=True)
    text = """\
# Summary

A table:

| a | b |
|---|---|
| 1 | 2 |

Code:

```bash
echo hello
```

Art:

```ascii
┌─────┐
│ hi  │
└─────┘
```
"""
    print_assistant_output(console, text)
    out = console.export_text()
    assert "hello" in out or "echo" in out
    assert "hi" in out or "┌" in out


def test_empty_safe():
    assert segment_output("") == []
    r = render_assistant_output("")
    assert r is not None
