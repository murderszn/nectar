"""
Surgical file edits — OpenCode `edit` / Hermes `patch` style.

`edit_file` replaces an exact old_string with new_string (unique match required
unless replace_all=True). Prefer this over full-file rewrites for local changes.
"""

from __future__ import annotations

from pathlib import Path

from opencode_harness.tools.pathutil import WorkspacePathError, resolve_workspace_path


def edit_file(
    path: str,
    old_string: str,
    new_string: str,
    *,
    workspace: Path,
    enforce_boundary: bool = True,
    replace_all: bool = False,
) -> str:
    """
    Apply a string replacement in a file.

    Returns OK with occurrence count, or ERROR with a helpful reason.
    """
    if old_string is None or old_string == "":
        return "ERROR: old_string must be non-empty (use write_file to create new files)"

    if old_string == new_string:
        return "ERROR: old_string and new_string are identical — nothing to change"

    try:
        target = resolve_workspace_path(
            path, workspace, enforce_boundary=enforce_boundary, for_write=True
        )
    except WorkspacePathError as exc:
        return f"ERROR: {exc}"

    if not target.exists():
        return f"ERROR: file not found: {target}  (use write_file to create it)"
    if not target.is_file():
        return f"ERROR: not a regular file: {target}"

    try:
        text = target.read_text(encoding="utf-8")
    except OSError as exc:
        return f"ERROR: cannot read {target}: {exc}"

    count = text.count(old_string)
    if count == 0:
        # Help the model: show nearby fuzzy context if a short prefix exists
        hint = _near_miss_hint(text, old_string)
        return (
            f"ERROR: old_string not found in {target}.\n"
            "The file may have changed — re-read it with read_file, then retry.\n"
            f"{hint}"
        ).strip()

    if count > 1 and not replace_all:
        return (
            f"ERROR: old_string matched {count} times in {target}.\n"
            "Provide a larger unique old_string, or set replace_all=true."
        )

    if replace_all:
        updated = text.replace(old_string, new_string if new_string is not None else "")
        n = count
    else:
        updated = text.replace(old_string, new_string if new_string is not None else "", 1)
        n = 1

    try:
        target.write_text(updated, encoding="utf-8")
    except OSError as exc:
        return f"ERROR: cannot write {target}: {exc}"

    return f"OK: edited {target}  ({n} replacement(s))"


def _near_miss_hint(text: str, old: str) -> str:
    """If the first non-empty line of old_string appears, show a snippet."""
    first = next((ln.strip() for ln in old.splitlines() if ln.strip()), "")
    if not first or len(first) < 4:
        return ""
    idx = text.find(first)
    if idx < 0:
        return ""
    start = max(0, idx - 40)
    end = min(len(text), idx + len(first) + 80)
    snippet = text[start:end].replace("\n", "\\n")
    return f"Near miss snippet: …{snippet}…"
