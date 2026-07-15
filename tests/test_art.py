"""ASCII art / splash render smoke tests."""

from rich.console import Console

from opencode_harness.ui.art import (
    MARK,
    WORDMARK,
    agent_header,
    fluid_wave,
    render_splash,
    tool_call_line,
    _pretty_tool_name,
)


def test_nectar_wordmark_present():
    assert "NECTAR" in WORDMARK or "██" in WORDMARK
    assert "N E C" in MARK or "◉" in MARK


def test_fluid_wave_width():
    t = fluid_wave(40, variant=0)
    plain = t.plain
    assert len(plain) == 40


def test_splash_renders_nectar():
    console = Console(record=True, width=80, force_terminal=True)
    console.print(
        render_splash(
            model="kimi",
            base_url="https://gen.pollinations.ai/v1",
            workspace="/tmp/ws",
            auth="pollen · sk_a***",
            version="0.1.0",
            log_file="/tmp/h.log",
            full=True,
        )
    )
    text = console.export_text()
    assert "kimi" in text
    assert "NECTAR" in text or "██" in text or "N E C" in text
    assert "honey" in text.lower() or "A G E N T" in text or "AGENT" in text.replace(" ", "")


def test_agent_header():
    plain = agent_header().plain
    assert "nectar" in plain.lower()


def test_tool_call_line_claude_style():
    t = tool_call_line("Bash", "ls -la")
    plain = t.plain
    assert "Bash" in plain
    assert "ls -la" in plain
    assert _pretty_tool_name("execute_bash_command") == "Bash"
