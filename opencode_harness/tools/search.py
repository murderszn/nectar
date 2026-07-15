"""
Workspace search tools — OpenCode `glob`/`grep` + Hermes `search_files` style.

Uses ripgrep when available (fast, respects .gitignore); pure-Python fallbacks
otherwise so the agent works on a stock macOS install.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from opencode_harness.tools.pathutil import WorkspacePathError, resolve_workspace_path

_SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "dist",
    "build",
    ".next",
    ".turbo",
    "target",
    ".opencode_harness",
}


def list_directory(
    path: str = ".",
    *,
    workspace: Path,
    enforce_boundary: bool = True,
    max_entries: int = 200,
) -> str:
    """List a directory (names + types), sorted."""
    try:
        target = resolve_workspace_path(
            path or ".", workspace, enforce_boundary=enforce_boundary, for_write=False
        )
    except WorkspacePathError as exc:
        return f"ERROR: {exc}"

    if not target.exists():
        return f"ERROR: not found: {target}"
    if not target.is_dir():
        return f"ERROR: not a directory: {target}"

    try:
        entries = sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except OSError as exc:
        return f"ERROR: cannot list {target}: {exc}"

    lines = [f"path: {target}", f"count: {len(entries)}", "---"]
    for i, ent in enumerate(entries):
        if i >= max_entries:
            lines.append(f"… {len(entries) - max_entries} more")
            break
        kind = "dir " if ent.is_dir() else "file"
        try:
            size = ent.stat().st_size if ent.is_file() else 0
        except OSError:
            size = 0
        if ent.is_dir():
            lines.append(f"{kind}  {ent.name}/")
        else:
            lines.append(f"{kind}  {ent.name}  ({size} B)")
    return "\n".join(lines)


def glob_files(
    pattern: str,
    *,
    workspace: Path,
    path: str = ".",
    max_results: int = 100,
) -> str:
    """
    Find files by glob pattern (e.g. **/*.py, src/**/*.ts).

    Prefer ripgrep --files; fallback to pathlib rglob.
    """
    if not pattern or not pattern.strip():
        return "ERROR: empty pattern"

    try:
        root = resolve_workspace_path(
            path or ".", workspace, enforce_boundary=True, for_write=False
        )
    except WorkspacePathError as exc:
        return f"ERROR: {exc}"

    if not root.exists():
        return f"ERROR: path not found: {root}"

    pattern = pattern.strip()
    results: list[str] = []

    rg = shutil.which("rg")
    if rg:
        # rg --files -g pattern
        glob_pat = pattern if any(c in pattern for c in "*?[") else f"*{pattern}*"
        try:
            proc = subprocess.run(
                [rg, "--files", "--sortr=modified", "-g", glob_pat, str(root)],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            for line in (proc.stdout or "").splitlines():
                line = line.strip()
                if line:
                    results.append(line)
        except (OSError, subprocess.TimeoutExpired):
            results = []

    if not results:
        # pathlib fallback
        try:
            if root.is_file():
                candidates = [root]
            else:
                # Support ** and simple globs
                if "**" in pattern or "/" in pattern:
                    candidates = list(root.glob(pattern))
                else:
                    candidates = list(root.rglob(pattern))
            for p in candidates:
                if not p.is_file():
                    continue
                if any(part in _SKIP_DIRS for part in p.parts):
                    continue
                results.append(str(p))
        except OSError as exc:
            return f"ERROR: glob failed: {exc}"

    # De-dupe preserve order
    seen: set[str] = set()
    unique: list[str] = []
    for r in results:
        if r not in seen:
            seen.add(r)
            unique.append(r)

    total = len(unique)
    clipped = unique[: max(1, max_results)]
    rel = []
    ws = workspace.resolve()
    for p in clipped:
        try:
            rel.append(str(Path(p).resolve().relative_to(ws)))
        except ValueError:
            rel.append(p)

    header = [
        f"pattern: {pattern}",
        f"root: {root}",
        f"matches: {total}" + (f" (showing {len(rel)})" if total > len(rel) else ""),
        "---",
    ]
    return "\n".join(header + rel) if rel else "\n".join(header + ["(no matches)"])


def grep_search(
    pattern: str,
    *,
    workspace: Path,
    path: str = ".",
    glob: str = "",
    max_results: int = 50,
    case_insensitive: bool = False,
) -> str:
    """
    Search file contents for a regex/string pattern.

    Prefer `rg`; fallback to pure Python walk.
    """
    if not pattern:
        return "ERROR: empty pattern"

    try:
        root = resolve_workspace_path(
            path or ".", workspace, enforce_boundary=True, for_write=False
        )
    except WorkspacePathError as exc:
        return f"ERROR: {exc}"

    if not root.exists():
        return f"ERROR: path not found: {root}"

    max_results = max(1, min(int(max_results or 50), 200))
    matches: list[str] = []

    rg = shutil.which("rg")
    if rg:
        cmd = [
            rg,
            "--line-number",
            "--color",
            "never",
            "--no-heading",
            "--max-count",
            "20",
            "-m",
            str(max_results),
        ]
        if case_insensitive:
            cmd.append("-i")
        if glob:
            cmd.extend(["-g", glob])
        cmd.extend(["--", pattern, str(root)])
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=45,
                check=False,
            )
            for line in (proc.stdout or "").splitlines():
                if line.strip():
                    matches.append(line)
                    if len(matches) >= max_results:
                        break
            if matches:
                return _format_grep(pattern, root, matches, truncated=len(matches) >= max_results)
            if proc.returncode not in (0, 1):
                # fall through to python on weird failures
                pass
            else:
                return _format_grep(pattern, root, [], truncated=False)
        except (OSError, subprocess.TimeoutExpired):
            pass

    # Pure Python fallback
    try:
        flags = re.I if case_insensitive else 0
        rx = re.compile(pattern, flags)
    except re.error as exc:
        return f"ERROR: invalid regex: {exc}"

    glob_rx = None
    if glob:
        # crude glob → regex
        g = re.escape(glob).replace(r"\*", ".*").replace(r"\?", ".")
        glob_rx = re.compile(f"^{g}$", re.I)

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".")]
        for name in filenames:
            if glob_rx and not glob_rx.match(name):
                continue
            fp = Path(dirpath) / name
            try:
                if fp.stat().st_size > 1_000_000:
                    continue
                sample = fp.read_bytes()[:512]
                if b"\x00" in sample:
                    continue
                text = fp.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for i, line in enumerate(text.splitlines(), start=1):
                if rx.search(line):
                    try:
                        rel = fp.resolve().relative_to(workspace.resolve())
                        shown = str(rel)
                    except ValueError:
                        shown = str(fp)
                    matches.append(f"{shown}:{i}:{line[:240]}")
                    if len(matches) >= max_results:
                        return _format_grep(pattern, root, matches, truncated=True)

    return _format_grep(pattern, root, matches, truncated=False)


def _format_grep(pattern: str, root: Path, matches: list[str], *, truncated: bool) -> str:
    header = [
        f"pattern: {pattern}",
        f"root: {root}",
        f"matches: {len(matches)}" + (" (truncated)" if truncated else ""),
        "---",
    ]
    if not matches:
        return "\n".join(header + ["(no matches)"])
    return "\n".join(header + matches)
