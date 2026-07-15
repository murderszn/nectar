"""
Design themes for honey — rainbow-first waiting / loading chrome.

Themes control:
  • splash gradient palette
  • animated wait indicators (bars, circles, braille, rainbow cycles)
  • accent colors for tools / prompts

Default theme: ``rainbow``.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from rich.console import Console, ConsoleOptions, RenderResult
from rich.text import Text

# ---------------------------------------------------------------------------
# Palettes
# ---------------------------------------------------------------------------

# Classic vivid rainbow (loading bars love these)
RAINBOW = (
    "#ff0040",  # hot red-pink
    "#ff6b00",  # orange
    "#ffd000",  # gold
    "#39ff14",  # neon green
    "#00e5ff",  # cyan
    "#3d5afe",  # electric blue
    "#d500f9",  # violet
    "#ff00aa",  # magenta
)

# Softer pastel rainbow
RAINBOW_SOFT = (
    "#ff8a80",
    "#ffd180",
    "#ffff8d",
    "#b9f6ca",
    "#80d8ff",
    "#b388ff",
    "#f8bbd0",
)

# Honey / nectar (warmer, less rainbow)
HONEY = (
    "#f0b429",
    "#e89b3c",
    "#ff7b72",
    "#3dd6c6",
    "#58a6ff",
    "#b392f0",
    "#7ee787",
)

# Quiet monochrome-ish
QUIET = (
    "#8b949e",
    "#c9d1d9",
    "#6e7681",
    "#58a6ff",
)

# Circle / spinner frame sets
CIRCLES = ("◐", "◓", "◑", "◒")
DOTS_BRAILLE = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
ARCS = ("◜", "◠", "◝", "◞", "◡", "◟")
BLOCKS = ("▖", "▘", "▝", "▗")
MOONS = ("🌑", "🌒", "🌓", "🌔", "🌕", "🌖", "🌗", "🌘")  # may be wide in some fonts
PULSES = ("○", "◔", "◑", "◕", "●", "◕", "◑", "◔")
RAINBOW_DOTS = ("•", "●", "◆", "●")

# Progress bar character sets
BAR_BLOCK = ("█", "░")
BAR_PIPE = ("┃", "╷")
BAR_SHADE = ("▓", "░")
BAR_DOT = ("●", "○")
BAR_EQ = ("=", "-")


@dataclass
class Theme:
    """Visual theme definition."""

    name: str
    palette: tuple[str, ...]
    spinner_frames: tuple[str, ...] = DOTS_BRAILLE
    bar_fill: str = "█"
    bar_empty: str = "░"
    bar_width: int = 18
    wait_style: str = "rainbow_bar"  # rainbow_bar | circle | pulse | dots
    prompt_color: str = "#ffd000"
    tool_color: str = "#00e5ff"
    ok_color: str = "#39ff14"
    err_color: str = "#ff0040"
    dim_color: str = "#6e7681"
    ink_color: str = "#e6edf3"
    description: str = ""


THEMES: dict[str, Theme] = {
    "rainbow": Theme(
        name="rainbow",
        palette=RAINBOW,
        spinner_frames=DOTS_BRAILLE,
        bar_fill="█",
        bar_empty="░",
        bar_width=20,
        wait_style="rainbow_bar",
        prompt_color="#ffd000",
        tool_color="#00e5ff",
        description="Vivid rainbow bars + braille spinner (default)",
    ),
    "prism": Theme(
        name="prism",
        palette=RAINBOW,
        spinner_frames=CIRCLES,
        bar_fill="▓",
        bar_empty="░",
        bar_width=16,
        wait_style="circle",
        prompt_color="#ff00aa",
        tool_color="#d500f9",
        description="Spinning color circles + prism accents",
    ),
    "pulse": Theme(
        name="pulse",
        palette=RAINBOW_SOFT,
        spinner_frames=PULSES,
        bar_fill="●",
        bar_empty="○",
        bar_width=12,
        wait_style="pulse",
        prompt_color="#ff8a80",
        tool_color="#80d8ff",
        description="Soft pastel pulse dots",
    ),
    "honey": Theme(
        name="honey",
        palette=HONEY,
        spinner_frames=DOTS_BRAILLE,
        bar_fill="█",
        bar_empty="░",
        bar_width=16,
        wait_style="rainbow_bar",
        prompt_color="#f0b429",
        tool_color="#3dd6c6",
        description="Warm nectar / honey gradient",
    ),
    "quiet": Theme(
        name="quiet",
        palette=QUIET,
        spinner_frames=DOTS_BRAILLE,
        bar_fill="━",
        bar_empty="─",
        bar_width=14,
        wait_style="dots",
        prompt_color="#c9d1d9",
        tool_color="#58a6ff",
        description="Minimal dim chrome",
    ),
}

DEFAULT_THEME = "rainbow"


def get_theme(name: Optional[str] = None) -> Theme:
    key = (name or DEFAULT_THEME).strip().lower()
    return THEMES.get(key, THEMES[DEFAULT_THEME])


def list_themes() -> list[Theme]:
    return list(THEMES.values())


def rainbow_text(s: str, palette: tuple[str, ...] = RAINBOW, *, offset: int = 0) -> Text:
    """Paint a string with a cycling rainbow gradient."""
    t = Text()
    n = len(palette)
    for i, ch in enumerate(s):
        t.append(ch, style=palette[(i + offset) % n])
    return t


def rainbow_bar(
    progress: float,
    *,
    width: int = 20,
    palette: tuple[str, ...] = RAINBOW,
    fill: str = "█",
    empty: str = "░",
    phase: int = 0,
) -> Text:
    """
    Indeterminate or determinate rainbow loading bar.

    progress in [0, 1] for determinate; if progress < 0, bounce indeterminate.
    """
    t = Text()
    if progress < 0:
        # Indeterminate: sliding rainbow window
        win = max(3, width // 3)
        start = phase % (width + win) - win
        for i in range(width):
            if start <= i < start + win:
                t.append(fill, style=palette[(i + phase) % len(palette)])
            else:
                t.append(empty, style="#30363d")
        return t

    filled = int(max(0.0, min(1.0, progress)) * width)
    for i in range(width):
        if i < filled:
            t.append(fill, style=palette[(i + phase) % len(palette)])
        else:
            t.append(empty, style="#30363d")
    return t


class RainbowWait:
    """
    Rich-renderable animated wait line for Live display.

    Renders something like:
       ⠋  Thinking  ▓▓▓▓▓░░░░░  3s  ···
    with rainbow cycling colors.
    """

    def __init__(
        self,
        label: str = "Thinking",
        *,
        theme: Optional[Theme] = None,
        t0: Optional[float] = None,
    ):
        self.label = label
        self.theme = theme or get_theme()
        self.t0 = t0 if t0 is not None else time.monotonic()
        self._tick = 0

    def advance(self) -> None:
        self._tick += 1

    def set_label(self, label: str) -> None:
        self.label = label

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        self._tick += 1
        th = self.theme
        elapsed = int(time.monotonic() - self.t0)
        frame = th.spinner_frames[self._tick % len(th.spinner_frames)]
        phase = self._tick

        # Spinner glyph in rainbow
        spin_color = th.palette[phase % len(th.palette)]
        out = Text("  ")
        out.append(frame, style=f"bold {spin_color}")
        out.append("  ", style="")

        # Label — soft rainbow wash on letters
        out.append_text(rainbow_text(self.label, th.palette, offset=phase // 2))

        out.append("  ", style="")

        style = th.wait_style
        if style == "circle":
            # Row of rotating circles in rainbow
            for i in range(8):
                fr = CIRCLES[(phase + i) % len(CIRCLES)]
                out.append(fr, style=th.palette[(phase + i) % len(th.palette)])
            out.append("  ", style="")
        elif style == "pulse":
            for i in range(th.bar_width):
                # Expanding pulse from center
                mid = th.bar_width // 2
                dist = abs(i - mid)
                wave = (phase // 2) % (mid + 3)
                ch = th.bar_fill if dist <= wave % (mid + 1) else th.bar_empty
                out.append(ch, style=th.palette[(i + phase) % len(th.palette)] if ch == th.bar_fill else "#30363d")
            out.append("  ", style="")
        elif style == "dots":
            for i in range(6):
                on = (phase // 2 + i) % 4 != 0
                out.append("●" if on else "·", style=th.palette[(phase + i) % len(th.palette)] if on else th.dim_color)
            out.append("  ", style="")
        else:
            # rainbow_bar (default) — indeterminate slide
            out.append_text(
                rainbow_bar(
                    -1.0,
                    width=th.bar_width,
                    palette=th.palette,
                    fill=th.bar_fill,
                    empty=th.bar_empty,
                    phase=phase,
                )
            )
            out.append("  ", style="")

        if elapsed >= 1:
            out.append(f"{elapsed}s", style=th.dim_color)

        # trailing sparkles
        spark = ("·", "✦", "·", "✧", "·", "★")[phase % 6]
        out.append(f"  {spark}", style=th.palette[(phase + 3) % len(th.palette)])

        yield out


def complete_flash(theme: Optional[Theme] = None, width: int = 24) -> Text:
    """Short rainbow flash line for turn completion."""
    th = theme or get_theme()
    t = Text("  ")
    t.append_text(rainbow_text("━" * width, th.palette))
    return t
