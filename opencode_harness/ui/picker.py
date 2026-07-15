"""
Interactive selectors for honey session (scrollback-friendly).

Uses numbered sections printed with Rich + a simple prompt — no alt-screen
dialog, so terminal history stays intact (Claude/OpenCode style).
"""

from __future__ import annotations

from typing import Optional

from rich.console import Console
from rich.table import Table
from rich.text import Text

from opencode_harness.models_catalog import (
    CatalogEntry,
    build_catalog,
    find_by_index,
    find_by_name,
)
from opencode_harness.ui.art import C_DIM, C_FOG, C_HONEY, C_MINT, C_TEAL, C_VIOLET


def pick_model(
    console: Console,
    *,
    current: str,
    configured: list[str],
) -> Optional[str]:
    """
    Show a sectioned model list and return the chosen model id, or None if cancelled.
    """
    catalog = build_catalog(current=current, configured=configured)
    if not catalog:
        console.print(f"  [{C_FOG}]No models configured.[/]")
        return None

    _print_catalog(console, catalog, current=current)

    console.print()
    console.print(
        f"  [{C_DIM}]Enter number, model name, or leave blank to cancel[/]"
    )
    try:
        raw = console.input(f"  [{C_HONEY}]model ›[/] ").strip()
    except (EOFError, KeyboardInterrupt):
        console.print()
        return None

    if not raw:
        return None

    # Numeric selection
    if raw.isdigit():
        model = find_by_index(catalog, int(raw))
        if model:
            return model
        console.print(f"  [yellow]No model at #{raw}[/]")
        return None

    # Name (catalog or free-form)
    return find_by_name(catalog, raw)


def _print_catalog(console: Console, catalog: list[CatalogEntry], *, current: str) -> None:
    console.print()
    console.print(Text("  select model", style=f"bold {C_TEAL}"))
    console.print(Text(f"  current · {current}", style=C_DIM))
    console.print()

    # Group by section preserving order
    by_section: dict[str, list[CatalogEntry]] = {}
    order: list[str] = []
    for row in catalog:
        if row.section not in by_section:
            by_section[row.section] = []
            order.append(row.section)
        by_section[row.section].append(row)

    for section in order:
        console.print(Text(f"  ── {section} ──", style=f"bold {C_VIOLET}"))
        table = Table(
            show_header=False,
            box=None,
            padding=(0, 1),
            pad_edge=False,
        )
        table.add_column("n", justify="right", style=C_HONEY, width=4)
        table.add_column("mark", width=2)
        table.add_column("model", style="bold")

        for row in by_section[section]:
            mark = "→" if row.is_current else " "
            style = C_MINT if row.is_current else ""
            table.add_row(
                str(row.index),
                mark,
                Text(row.model, style=style or "bold"),
            )
        console.print(table)
        console.print()
