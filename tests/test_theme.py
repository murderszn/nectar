"""Rainbow theme / loading chrome tests."""

from rich.console import Console

from opencode_harness.ui.theme import (
    RainbowWait,
    get_theme,
    list_themes,
    rainbow_bar,
    rainbow_text,
)


def test_default_theme_is_rainbow():
    th = get_theme()
    assert th.name == "rainbow"
    assert len(th.palette) >= 6


def test_list_themes():
    names = {t.name for t in list_themes()}
    assert {"rainbow", "prism", "pulse", "honey", "quiet"} <= names


def test_rainbow_text_and_bar():
    t = rainbow_text("NECTAR")
    assert "NECTAR" in t.plain
    bar = rainbow_bar(-1.0, width=12, phase=3)
    assert len(bar.plain) == 12
    bar2 = rainbow_bar(0.5, width=10, phase=0)
    assert len(bar2.plain) == 10


def test_rainbow_wait_renders():
    console = Console(record=True, width=80, force_terminal=True)
    wait = RainbowWait("Thinking", theme=get_theme("rainbow"))
    for _ in range(5):
        wait.advance()
    console.print(wait)
    text = console.export_text()
    assert "Thinking" in text
