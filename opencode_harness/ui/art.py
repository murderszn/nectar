"""
Nectar agent visual identity — full ASCII brand + Claude/OpenCode session chrome.

Splash: nectar drop mark + NECTAR wordmark + fluid wave separators.
In-session tools stay Claude-quiet (⏺ / ⎿ trees).
CLI command remains ``honey``.
"""

from __future__ import annotations

import random
from typing import Iterable

from rich.console import Console, Group, RenderableType
from rich.text import Text

# Palette — nectar / pollen / deep terminal fluid
C_HONEY = "#f0b429"
C_AMBER = "#e89b3c"
C_CORAL = "#ff7b72"
C_TEAL = "#3dd6c6"
C_CYAN = "#58a6ff"
C_VIOLET = "#b392f0"
C_MINT = "#7ee787"
C_DIM = "#6e7681"
C_FOG = "#8b949e"
C_INK = "#c9d1d9"
C_SOFT = "#484f58"

# Claude / OpenCode-like interaction glyphs (in-session)
ICON_TOOL = "⏺"
ICON_RESULT = "⎿"
ICON_OK = "✓"
ICON_FAIL = "✗"
ICON_THINK = "✶"
ICON_USER = "❯"
ICON_DOT = "·"
ICON_SPARK = "✦"
ICON_NODE = "◆"
ICON_DROP = "◉"
ICON_POLLEN = "※"
ICON_GEAR = "⚙"
ICON_BRANCH = "╰"
ICON_PIPE = "│"
ICON_AGENT = "◈"
ICON_WAIT = "◌"

# ---------------------------------------------------------------------------
# Nectar agent ASCII art
# ---------------------------------------------------------------------------

# Abstract "nectar drop + circuit" mark
MARK = r"""
      .  ·  *
    ·   ╱╲   ·
   *  ╱  ╲╲   .
     ╱ ◉  ╲╲     ·
  · ╱  ░▒▓  ╲╲ *
   ╱__╱▔▔▔╲__╲╲
  ▔    N E C    ▔
""".strip(
    "\n"
)

# Wide NECTAR wordmark
WORDMARK = r"""
 ███╗   ██╗███████╗ ██████╗████████╗ █████╗ ██████╗
 ████╗  ██║██╔════╝██╔════╝╚══██╔══╝██╔══██╗██╔══██╗
 ██╔██╗ ██║█████╗  ██║        ██║   ███████║██████╔╝
 ██║╚██╗██║██╔══╝  ██║        ██║   ██╔══██║██╔══██╗
 ██║ ╚████║███████╗╚██████╗   ██║   ██║  ██║██║  ██║
 ╚═╝  ╚═══╝╚══════╝ ╚═════╝   ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═╝
""".strip(
    "\n"
)

TAG = "A G E N T"

# Fluid wave strips
_WAVE_A = "∽∿∼≈≋∼∿∽∼≈≋∼∿∽∼≈≋∼∿∽∼≈≋∼∿∽∼≈≋∼∿∽∼≈≋∼∿∽"
_WAVE_B = "░▒▓█▓▒░▒▓█▓▒░▒▓█▓▒░▒▓█▓▒░▒▓█▓▒░▒▓█▓▒░▒▓█▓▒░"
_WAVE_C = "∙·•●◉●•·∙  ∙·•●◉●•·∙  ∙·•●◉●•·∙  ∙·•●◉●•·∙"
_WAVE_D = "╱╲╱╲╱╲╱╲╱╲╱╲╱╲╱╲╱╲╱╲╱╲╱╲╱╲╱╲╱╲╱╲╱╲╱╲╱╲╱╲╱╲"


def _gradient_line(s: str, colors: Iterable[str]) -> Text:
    cols = list(colors)
    t = Text()
    for i, ch in enumerate(s):
        t.append(ch, style=cols[i % len(cols)])
    return t


def _shade_block(lines: list[str], colors: list[str]) -> Text:
    t = Text()
    n = max(len(lines), 1)
    for i, line in enumerate(lines):
        idx = int((i / max(n - 1, 1)) * (len(colors) - 1))
        t.append(line + ("\n" if i < n - 1 else ""), style=colors[idx])
    return t


def fluid_wave(width: int = 56, variant: int | None = None) -> Text:
    """Organic separator strip."""
    v = variant if variant is not None else random.randint(0, 3)
    raw = [_WAVE_A, _WAVE_B, _WAVE_C, _WAVE_D][v % 4]
    s = (raw * ((width // len(raw)) + 2))[:width]
    palette = {
        0: [C_TEAL, C_CYAN, C_VIOLET, C_HONEY],
        1: [C_HONEY, C_AMBER, C_CORAL, C_VIOLET],
        2: [C_MINT, C_TEAL, C_CYAN, C_FOG],
        3: [C_VIOLET, C_CYAN, C_TEAL, C_HONEY],
    }[v % 4]
    return _gradient_line(s, palette)


def render_splash(
    *,
    model: str,
    base_url: str,
    workspace: str,
    auth: str,
    version: str,
    log_file: str = "",
    full: bool = True,
) -> RenderableType:
    """
    Full nectar agent splash (default).

    full=False is a compact one-liner (rarely used).
    """
    host = base_url.replace("https://", "").replace("http://", "")
    ws = workspace if len(workspace) <= 52 else "…" + workspace[-50:]

    if not full:
        drop = Text()
        drop.append("  ", style="")
        drop.append("◉", style=f"bold {C_HONEY}")
        drop.append(" nectar", style=f"bold {C_INK}")
        drop.append(f"  · honey v{version}", style=C_DIM)
        top: RenderableType = Group(Text(""), drop)
        wave1 = Text("")
        wave2 = Text("")
    else:
        mark = _shade_block(
            MARK.splitlines(),
            [C_VIOLET, C_CYAN, C_TEAL, C_HONEY, C_AMBER, C_HONEY, C_TEAL],
        )
        word = _shade_block(
            WORDMARK.splitlines(),
            [C_CYAN, C_TEAL, C_MINT, C_HONEY, C_AMBER, C_CORAL],
        )
        tag = Text(f"  {TAG}  ·  honey v{version}", style=f"bold {C_FOG}")
        wave1 = Group(Text(""), fluid_wave(62, variant=0), Text(""))
        wave2 = Group(Text(""), fluid_wave(62, variant=1), Text(""))
        top = Group(Text(""), mark, Text(""), word, tag)

    meta = Text()
    meta.append("  ", style="")
    meta.append(f"{ICON_NODE} ", style=C_HONEY)
    meta.append("model ", style=C_DIM)
    meta.append(model, style=f"bold {C_INK}")
    meta.append("  ·  ", style=C_SOFT)
    meta.append(host, style=C_FOG)
    meta.append("\n  ", style="")
    meta.append(f"{ICON_DROP} ", style=C_TEAL)
    meta.append(ws, style=C_FOG)
    meta.append("\n  ", style="")
    meta.append(f"{ICON_POLLEN} ", style=C_AMBER)
    meta.append(auth or "signed in", style=C_MINT)
    if log_file:
        meta.append("\n  ", style="")
        meta.append(f"{ICON_SPARK} ", style=C_VIOLET)
        meta.append("log ", style=C_DIM)
        meta.append(log_file, style=C_DIM)

    tip = Text()
    tip.append("\n  ", style="")
    tip.append(f"{ICON_USER} type a goal", style=C_FOG)
    tip.append("   ", style="")
    tip.append("/model  /help  /exit", style=C_DIM)
    tip.append("\n", style="")

    return Group(top, wave1, meta, wave2, tip)


def print_splash(console: Console, **kwargs) -> None:  # type: ignore[no-untyped-def]
    console.print(render_splash(**kwargs))


def turn_rule(label: str = "") -> Text:
    t = Text("  ")
    t.append_text(fluid_wave(40, variant=random.randint(0, 3)))
    if label:
        t.append(f"  {label}", style=C_DIM)
    t.append("\n")
    return t


def tool_call_line(display_name: str, detail: str) -> Text:
    """Claude-style tool head:  ⏺ Bash(ls -la)"""
    t = Text()
    t.append(f"  {ICON_TOOL} ", style=C_CYAN)
    t.append(display_name, style=f"bold {C_INK}")
    if detail:
        short = detail if len(detail) <= 72 else detail[:69] + "…"
        t.append("(", style=C_SOFT)
        t.append(short, style=C_FOG)
        t.append(")", style=C_SOFT)
    return t


def tool_result_prefix(*, ok: bool, summary: str) -> Text:
    """  ⎿  done · 12 lines"""
    t = Text()
    t.append(f"  {ICON_RESULT}  ", style=C_SOFT)
    t.append(summary, style=C_DIM if ok else C_CORAL)
    return t


def agent_header() -> Text:
    """Nectar agent label above assistant replies."""
    t = Text()
    t.append(f"  {ICON_AGENT} ", style=f"bold {C_TEAL}")
    t.append("nectar", style=f"bold {C_TEAL}")
    t.append(" agent", style=C_DIM)
    t.append("\n")
    return t


def goodbye_art() -> Text:
    t = Text()
    t.append_text(fluid_wave(36, variant=2))
    t.append("\n  ", style="")
    t.append("nectar session closed. ", style=C_DIM)
    t.append("stay sticky.\n", style=C_HONEY)
    return t


def tool_header(name: str, preview: str) -> Text:
    return tool_call_line(_pretty_tool_name(name), preview)


def tool_result_header(name: str, *, ok: bool) -> Text:
    return tool_result_prefix(ok=ok, summary=("ok" if ok else "failed") + f" · {name}")


def _pretty_tool_name(name: str) -> str:
    mapping = {
        "execute_bash_command": "Bash",
        "read_file": "Read",
        "view_workspace_file": "Read",
        "write_file": "Write",
        "write_workspace_file": "Write",
        "edit_file": "Edit",
        "glob_files": "Glob",
        "grep_search": "Grep",
        "list_directory": "List",
        "browse_web_content": "Web",
    }
    return mapping.get(name, name)
