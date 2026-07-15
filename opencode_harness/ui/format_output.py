"""
Format assistant output for clean terminal display.

Preserves monospaced layouts that Markdown would destroy:
  • fenced code blocks (``` … ```)
  • ASCII art / box-drawing diagrams
  • fixed-width grids & charts
  • markdown pipe tables → Rich Table
  • indented preformatted blocks

Prose still renders as Markdown.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Iterator, Literal, Optional

from rich.console import Console, Group, RenderableType
from rich.markdown import Markdown
from rich.padding import Padding
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

# Characters that strongly signal fixed-width / diagram content
_BOX_CHARS = set(
    "┌┐└┘├┤┬┴┼─│═║╔╗╚╝╠╣╦╩╬▀▄█▌▐░▒▓"
    "╭╮╯╰╱╲╳▶▷◀◁▲▼◆◇○●◉◈▣▪▫■□▪"
    "┃━┏┓┗┛┣┫┳┻╋╸╹╺╻"
    "+-|/\\*_=#~^v<>"
)

_FENCE_RE = re.compile(r"^```([\w.+-]*)\s*$")
_TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$")
_TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")


SegmentKind = Literal["prose", "code", "pre", "table"]


@dataclass
class Segment:
    kind: SegmentKind
    text: str
    language: str = ""  # for code fences


# ---------------------------------------------------------------------------
# Segmentation
# ---------------------------------------------------------------------------

def segment_output(text: str) -> list[Segment]:
    """Split assistant text into prose / code / pre / table segments."""
    if not text:
        return []

    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    segments: list[Segment] = []
    i = 0
    prose_buf: list[str] = []

    def flush_prose() -> None:
        nonlocal prose_buf
        if prose_buf:
            body = "\n".join(prose_buf).strip("\n")
            if body.strip():
                segments.append(Segment("prose", body))
            prose_buf = []

    while i < len(lines):
        line = lines[i]
        fence = _FENCE_RE.match(line)

        # --- fenced code block -----------------------------------------
        if fence:
            flush_prose()
            lang = (fence.group(1) or "").strip().lower()
            i += 1
            body: list[str] = []
            while i < len(lines) and not _FENCE_RE.match(lines[i]):
                body.append(lines[i])
                i += 1
            if i < len(lines):
                i += 1  # closing fence
            block = "\n".join(body)
            # ascii / text / empty lang → pre panel; known langs → syntax
            if lang in {"", "text", "ascii", "art", "plain", "diagram", "chart", "grid", "txt"}:
                segments.append(Segment("pre", block, language=lang or "ascii"))
            else:
                segments.append(Segment("code", block, language=lang))
            continue

        # --- markdown pipe table ---------------------------------------
        if _looks_like_table_start(lines, i):
            flush_prose()
            table_lines: list[str] = []
            while i < len(lines) and (_TABLE_ROW_RE.match(lines[i]) or _TABLE_SEP_RE.match(lines[i])):
                table_lines.append(lines[i])
                i += 1
            segments.append(Segment("table", "\n".join(table_lines)))
            continue

        # --- unfenced monospaced block (ASCII art / grid) --------------
        mono = _scan_mono_block(lines, i)
        if mono is not None:
            end, block = mono
            flush_prose()
            segments.append(Segment("pre", block, language="ascii"))
            i = end
            continue

        prose_buf.append(line)
        i += 1

    flush_prose()
    return segments


def _looks_like_table_start(lines: list[str], i: int) -> bool:
    if i + 1 >= len(lines):
        return False
    if not _TABLE_ROW_RE.match(lines[i]):
        return False
    return bool(_TABLE_SEP_RE.match(lines[i + 1]))


def _scan_mono_block(lines: list[str], start: int) -> Optional[tuple[int, str]]:
    """
    Detect a run of ≥3 lines that look monospaced (ASCII art, charts, grids).

    Heuristics: high density of box/drawing chars, multi-space runs,
    leading spaces alignment, or consistent line lengths for art.
    """
    if start >= len(lines):
        return None

    # Never *start* a mono block on a blank line (would swallow following tables)
    if not lines[start].strip():
        return None

    # Don't steal markdown tables — those have their own segmenter
    if _TABLE_ROW_RE.match(lines[start]) or _TABLE_SEP_RE.match(lines[start]):
        return None

    # Don't steal normal list/paragraph lines
    if not _line_is_mono_candidate(lines[start]):
        return None

    end = start
    while end < len(lines) and _line_is_mono_candidate(lines[end]):
        # Stop mono block before a markdown table begins
        if end > start and _looks_like_table_start(lines, end):
            break
        if end > start and _TABLE_ROW_RE.match(lines[end]) and end + 1 < len(lines) and _TABLE_SEP_RE.match(lines[end + 1]):
            break
        end += 1

    # Require at least 3 consecutive mono lines (avoid false positives)
    if end - start < 3:
        return None

    block_lines = lines[start:end]
    # Drop trailing blank mono lines from the block (keep internal blanks)
    while block_lines and not block_lines[-1].strip():
        block_lines.pop()
        end -= 1
    if len(block_lines) < 3:
        return None

    # Score the block — must look "structural"
    if _mono_score(block_lines) < 0.35:
        return None

    return end, "\n".join(block_lines)


def _line_is_mono_candidate(line: str) -> bool:
    if not line.strip():
        return True  # blank allowed inside a block
    # Leading indent of 2+ spaces often means preformatted
    if line.startswith("  ") or line.startswith("\t"):
        # but not markdown lists
        stripped = line.lstrip()
        if stripped.startswith(("- ", "* ", "+ ")) or re.match(r"^\d+\.\s", stripped):
            return False
        return True
    # Box drawing / block elements
    box_hits = sum(1 for ch in line if ch in _BOX_CHARS or ord(ch) > 0x2500 and ord(ch) < 0x2600)
    if box_hits >= 2:
        return True
    # Multiple consecutive spaces (grid columns)
    if "  " in line and not line.lstrip().startswith("#"):
        # avoid normal sentences with double space after period
        if re.search(r"\S  +\S", line):
            return True
    # Sparkline / bar chart chars
    if any(ch in line for ch in "▁▂▃▄▅▆▇█▉▊▋▌▍▀░▒▓"):
        return True
    return False


def _mono_score(lines: list[str]) -> float:
    non_empty = [ln for ln in lines if ln.strip()]
    if not non_empty:
        return 0.0
    score = 0.0
    box = 0
    multi_space = 0
    bar = 0
    for ln in non_empty:
        if any(ch in _BOX_CHARS or (0x2500 <= ord(ch) <= 0x257F) for ch in ln):
            box += 1
        if re.search(r"\S  +\S", ln):
            multi_space += 1
        if any(ch in ln for ch in "▁▂▃▄▅▆▇█▉▊▋▌▍▀░▒▓"):
            bar += 1
    n = len(non_empty)
    score += 0.45 * (box / n)
    score += 0.35 * (multi_space / n)
    score += 0.40 * (bar / n)
    # Similar line lengths → art-ish
    lengths = [len(ln.rstrip()) for ln in non_empty]
    if lengths:
        avg = sum(lengths) / len(lengths)
        if avg > 0:
            var = sum(abs(L - avg) for L in lengths) / len(lengths)
            if var < avg * 0.25 and avg >= 8:
                score += 0.25
    return min(score, 1.0)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

_LANG_ALIASES = {
    "js": "javascript",
    "ts": "typescript",
    "py": "python",
    "sh": "bash",
    "shell": "bash",
    "yml": "yaml",
    "rb": "ruby",
    "rs": "rust",
    "csharp": "c#",
    "plaintext": "text",
}


def render_assistant_output(
    text: str,
    *,
    syntax_theme: str = "monokai",
    indent: int = 2,
) -> RenderableType:
    """Build a Rich renderable for the full assistant message."""
    segments = segment_output(text or "")
    if not segments:
        return Text("")

    parts: list[RenderableType] = []
    pad = (0, 0, 0, indent)

    for seg in segments:
        if seg.kind == "prose":
            parts.append(Padding(Markdown(seg.text, code_theme=syntax_theme), pad))
        elif seg.kind == "code":
            parts.append(Padding(_render_code(seg.text, seg.language, syntax_theme), pad))
        elif seg.kind == "pre":
            parts.append(Padding(_render_pre(seg.text, label=seg.language or "ascii"), pad))
        elif seg.kind == "table":
            parts.append(Padding(_render_table(seg.text), pad))

    return Group(*parts)


def _render_code(code: str, language: str, syntax_theme: str) -> RenderableType:
    lang = _LANG_ALIASES.get(language, language) or "text"
    # word_wrap=False keeps grids inside code fences intact
    try:
        syn = Syntax(
            code,
            lang if lang not in {"text", "ascii"} else "text",
            theme=syntax_theme,
            line_numbers=False,
            word_wrap=False,
            background_color="default",
            indent_guides=False,
        )
    except Exception:
        syn = Syntax(code, "text", theme=syntax_theme, word_wrap=False, background_color="default")

    return Panel(
        syn,
        border_style="#30363d",
        padding=(0, 1),
        title=f"[dim]{lang}[/]" if lang and lang != "text" else None,
        title_align="left",
    )


def _render_pre(block: str, *, label: str = "ascii") -> RenderableType:
    """Monospace panel — no wrap, preserve every space."""
    # Expand tabs for alignment
    body = block.expandtabs(4)
    text = Text(body, style="#c9d1d9", overflow="ignore", no_wrap=False)
    # no_wrap on Text is per-line; Console still may wrap — Panel + soft_wrap false
    return Panel(
        Text(body, style="#e6edf3"),
        border_style="#484f58",
        padding=(0, 1),
        title=f"[dim]{label}[/]",
        title_align="left",
        expand=False,
    )


def _render_table(md_table: str) -> RenderableType:
    """Parse a GFM pipe table into a Rich Table."""
    rows = []
    for raw in md_table.splitlines():
        line = raw.strip()
        if not line:
            continue
        if _TABLE_SEP_RE.match(line):
            continue
        # strip outer pipes
        if line.startswith("|"):
            line = line[1:]
        if line.endswith("|"):
            line = line[:-1]
        cells = [c.strip() for c in line.split("|")]
        rows.append(cells)

    if not rows:
        return Text(md_table)

    # Normalize column count
    cols = max(len(r) for r in rows)
    for r in rows:
        while len(r) < cols:
            r.append("")

    header = rows[0]
    body = rows[1:] if len(rows) > 1 else []

    table = Table(
        show_header=True,
        header_style="bold #f0b429",
        border_style="#484f58",
        box=None,
        pad_edge=False,
        expand=False,
        padding=(0, 1),
    )
    # Use simple box if available
    try:
        from rich import box as rich_box

        table = Table(
            show_header=True,
            header_style="bold #f0b429",
            border_style="#6e7681",
            box=rich_box.ROUNDED,
            pad_edge=False,
            expand=False,
            padding=(0, 1),
        )
    except Exception:
        pass

    for h in header:
        table.add_column(h or " ")
    for r in body:
        table.add_row(*r)
    return table


def print_assistant_output(
    console: Console,
    text: str,
    *,
    syntax_theme: str = "monokai",
    indent: int = 2,
) -> None:
    """Print formatted assistant content to the console."""
    # soft_wrap=False globally for this print so mono panels don't reflow
    console.print(
        render_assistant_output(text, syntax_theme=syntax_theme, indent=indent),
        soft_wrap=False,
        overflow="ignore",
    )
