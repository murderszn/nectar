"""
ToolRegistry — OpenCode/Hermes-inspired local coding toolbelt.

Core tools (always registered in build mode):
  read_file, write_file, edit_file, glob_files, grep_search,
  list_directory, execute_bash_command, browse_web_content

Legacy aliases kept for older prompts:
  view_workspace_file, write_workspace_file

Plan mode (read-only): write/edit/bash mutations disabled at registration.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Literal, Optional

from opencode_harness.config import ToolConfig
from opencode_harness.logging_setup import get_logger
from opencode_harness.models import ToolParameter, ToolSpec
from opencode_harness.tools.bash import ConfirmCallback, run_bash
from opencode_harness.tools.edit import edit_file
from opencode_harness.tools.files import read_file, write_file
from opencode_harness.tools.search import glob_files, grep_search, list_directory
from opencode_harness.tools.web import browse_web_content

log = get_logger("tools")

AgentMode = Literal["build", "plan"]


class ToolRegistry:
    """Named collection of ToolSpec entries with OpenCode-style coding tools."""

    def __init__(
        self,
        workspace: Path,
        tool_config: ToolConfig,
        *,
        confirm_destructive: Optional[ConfirmCallback] = None,
        mode: AgentMode = "build",
    ):
        self.workspace = workspace.resolve()
        self.tool_config = tool_config
        self.confirm_destructive = confirm_destructive
        self.mode: AgentMode = mode if mode in ("build", "plan") else "build"
        self._tools: dict[str, ToolSpec] = {}
        self._register_builtins()

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, spec: ToolSpec) -> None:
        if not spec.name or not re_valid_name(spec.name):
            raise ValueError(f"Invalid tool name: {spec.name!r}")
        self._tools[spec.name] = spec

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def get(self, name: str) -> Optional[ToolSpec]:
        return self._tools.get(name)

    def list_names(self) -> list[str]:
        return sorted(self._tools.keys())

    def openai_tools(self) -> list[dict[str, Any]]:
        return [spec.openai_schema() for spec in self._tools.values()]

    def set_mode(self, mode: AgentMode) -> None:
        """Rebuild tool set for build (full) or plan (read-only)."""
        self.mode = mode if mode in ("build", "plan") else "build"
        self._tools.clear()
        self._register_builtins()
        log.info("tool registry mode → %s  tools=%s", self.mode, self.list_names())

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def dispatch(self, name: str, arguments: dict[str, Any]) -> str:
        spec = self._tools.get(name)
        if spec is None:
            known = ", ".join(self.list_names()) or "(none)"
            log.error("unknown tool %r (known: %s)", name, known)
            return f"ERROR: unknown tool {name!r}. Known tools: {known}"

        allowed = {p.name for p in spec.parameters}
        kwargs = {k: v for k, v in arguments.items() if k in allowed}

        # Coerce simple numeric params from JSON strings
        for p in spec.parameters:
            if p.name in kwargs and p.type == "integer":
                try:
                    kwargs[p.name] = int(kwargs[p.name])
                except (TypeError, ValueError):
                    return f"ERROR: {p.name} must be an integer"
            if p.name in kwargs and p.type == "boolean":
                v = kwargs[p.name]
                if isinstance(v, str):
                    kwargs[p.name] = v.strip().lower() in {"1", "true", "yes", "on"}

        missing = [p.name for p in spec.parameters if p.required and p.name not in kwargs]
        if missing:
            log.error("tool %r missing args: %s", name, missing)
            return f"ERROR: tool {name!r} missing required args: {missing}"

        log.debug("dispatch %s kwargs_keys=%s", name, list(kwargs.keys()))
        t0 = time.monotonic()
        try:
            result = spec.invoke(**kwargs)
        except Exception as exc:  # noqa: BLE001
            log.exception("tool %r raised", name)
            return f"ERROR: tool {name!r} raised {type(exc).__name__}: {exc}"

        log.debug("dispatch %s done in %.2fs", name, time.monotonic() - t0)
        if result is None:
            return "(tool returned None)"
        return result if isinstance(result, str) else str(result)

    # ------------------------------------------------------------------
    # Built-ins
    # ------------------------------------------------------------------

    def _register_builtins(self) -> None:
        workspace = self.workspace
        cfg = self.tool_config
        confirm = self.confirm_destructive
        plan = self.mode == "plan"

        # ---- read / explore (always) ---------------------------------
        def _read(
            path: str,
            offset: int = 1,
            limit: int = 400,
        ) -> str:
            return read_file(
                path,
                workspace=workspace,
                enforce_boundary=cfg.enforce_workspace_boundary,
                offset=int(offset or 1),
                limit=int(limit or 400),
            )

        def _list(path: str = ".") -> str:
            return list_directory(
                path or ".",
                workspace=workspace,
                enforce_boundary=cfg.enforce_workspace_boundary,
            )

        def _glob(pattern: str, path: str = ".") -> str:
            return glob_files(
                pattern,
                workspace=workspace,
                path=path or ".",
            )

        def _grep(
            pattern: str,
            path: str = ".",
            glob: str = "",
            case_insensitive: bool = False,
            max_results: int = 50,
        ) -> str:
            return grep_search(
                pattern,
                workspace=workspace,
                path=path or ".",
                glob=glob or "",
                case_insensitive=bool(case_insensitive),
                max_results=int(max_results or 50),
            )

        def _browse(url: str) -> str:
            return browse_web_content(url)

        self.register(
            ToolSpec(
                name="read_file",
                description=(
                    "Open a text file with line numbers. Use offset/limit to page through "
                    "large files. Always read before editing. Prefer this over shell cat."
                ),
                parameters=[
                    ToolParameter("path", "string", "Relative or absolute path."),
                    ToolParameter(
                        "offset",
                        "integer",
                        "1-based start line (default 1).",
                        required=False,
                    ),
                    ToolParameter(
                        "limit",
                        "integer",
                        "Max lines to return (default 400, max 2000).",
                        required=False,
                    ),
                ],
                handler=_read,
            )
        )
        self.register(
            ToolSpec(
                name="list_directory",
                description="List files and subdirectories in a path (default: workspace root).",
                parameters=[
                    ToolParameter(
                        "path",
                        "string",
                        "Directory path relative to workspace (default '.').",
                        required=False,
                    ),
                ],
                handler=_list,
            )
        )
        self.register(
            ToolSpec(
                name="glob_files",
                description=(
                    "Find files by glob pattern, e.g. '**/*.py', 'src/**/*.ts', 'package.json'. "
                    "Use to locate code before reading."
                ),
                parameters=[
                    ToolParameter("pattern", "string", "Glob pattern."),
                    ToolParameter(
                        "path",
                        "string",
                        "Root directory to search (default '.').",
                        required=False,
                    ),
                ],
                handler=_glob,
            )
        )
        self.register(
            ToolSpec(
                name="grep_search",
                description=(
                    "Search file contents with a regex/string (ripgrep when available). "
                    "Returns path:line:content matches. Use to find symbols, TODOs, call sites."
                ),
                parameters=[
                    ToolParameter("pattern", "string", "Regex or fixed string to search for."),
                    ToolParameter(
                        "path",
                        "string",
                        "Directory or file to search (default '.').",
                        required=False,
                    ),
                    ToolParameter(
                        "glob",
                        "string",
                        "Optional file filter e.g. '*.py' or '*.ts'.",
                        required=False,
                    ),
                    ToolParameter(
                        "case_insensitive",
                        "boolean",
                        "Case-insensitive search (default false).",
                        required=False,
                    ),
                    ToolParameter(
                        "max_results",
                        "integer",
                        "Max matches to return (default 50).",
                        required=False,
                    ),
                ],
                handler=_grep,
            )
        )
        self.register(
            ToolSpec(
                name="browse_web_content",
                description=(
                    "Fetch a web page and return cleaned text/markdown for docs and research."
                ),
                parameters=[
                    ToolParameter("url", "string", "HTTP or HTTPS URL."),
                ],
                handler=_browse,
            )
        )

        # Legacy read alias
        self.register(
            ToolSpec(
                name="view_workspace_file",
                description="Alias of read_file (full first page). Prefer read_file.",
                parameters=[ToolParameter("path", "string", "File path.")],
                handler=lambda path: _read(path, 1, 2000),
            )
        )

        if plan:
            log.info("plan mode: write/edit/bash mutation tools omitted")
            return

        # ---- mutate (build mode only) --------------------------------
        def _write(path: str, content: str) -> str:
            return write_file(
                path,
                content,
                workspace=workspace,
                enforce_boundary=cfg.enforce_workspace_boundary,
            )

        def _edit(
            path: str,
            old_string: str,
            new_string: str,
            replace_all: bool = False,
        ) -> str:
            return edit_file(
                path,
                old_string,
                new_string,
                workspace=workspace,
                enforce_boundary=cfg.enforce_workspace_boundary,
                replace_all=bool(replace_all),
            )

        def _bash(command: str) -> str:
            return run_bash(
                command,
                timeout=cfg.bash_timeout,
                cwd=str(workspace),
                confirm=confirm,
                extra_destructive_patterns=cfg.extra_destructive_patterns,
            )

        self.register(
            ToolSpec(
                name="write_file",
                description=(
                    "Create or overwrite a whole file. Prefer edit_file for small changes. "
                    "Parent directories are created automatically."
                ),
                parameters=[
                    ToolParameter("path", "string", "Path under the workspace."),
                    ToolParameter("content", "string", "Full file contents."),
                ],
                handler=_write,
            )
        )
        self.register(
            ToolSpec(
                name="edit_file",
                description=(
                    "Surgical edit: replace exact old_string with new_string in a file. "
                    "old_string must match uniquely unless replace_all is true. "
                    "Always read_file first so you have current content."
                ),
                parameters=[
                    ToolParameter("path", "string", "File to edit."),
                    ToolParameter("old_string", "string", "Exact text to find."),
                    ToolParameter("new_string", "string", "Replacement text."),
                    ToolParameter(
                        "replace_all",
                        "boolean",
                        "Replace every occurrence (default false).",
                        required=False,
                    ),
                ],
                handler=_edit,
            )
        )
        self.register(
            ToolSpec(
                name="execute_bash_command",
                description=(
                    "Run a shell command in the workspace (builds, tests, git, package managers). "
                    "Destructive commands require human confirmation. Prefer dedicated "
                    "read/glob/grep tools over cat/find/grep when possible."
                ),
                parameters=[
                    ToolParameter("command", "string", "Shell command to run."),
                ],
                handler=_bash,
            )
        )
        # Legacy write alias
        self.register(
            ToolSpec(
                name="write_workspace_file",
                description="Alias of write_file. Prefer write_file.",
                parameters=[
                    ToolParameter("path", "string", "Path."),
                    ToolParameter("content", "string", "Contents."),
                ],
                handler=_write,
            )
        )


def re_valid_name(name: str) -> bool:
    return bool(re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", name))
