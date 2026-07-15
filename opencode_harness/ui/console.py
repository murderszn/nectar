"""
Rich-powered terminal presentation for OpenCodeHarness.

Visual language:
  - System / status  → dim cyan
  - Tool panels      → blue border, yellow title
  - Bash output      → syntax-highlighted / monospaced
  - Assistant final  → green-bordered markdown panel
  - Errors           → red bold
"""

from __future__ import annotations

import json
from typing import Any, Optional

from rich.console import Console, Group
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.spinner import Spinner
from rich.syntax import Syntax
from rich.text import Text

from opencode_harness.models import ToolCall


class TerminalUI:
    """Thin façade over Rich for the CLI session."""

    def __init__(self, *, syntax_theme: str = "monokai", show_tool_args: bool = True):
        self.console = Console()
        self.syntax_theme = syntax_theme
        self.show_tool_args = show_tool_args
        self._live: Optional[Live] = None

    # ------------------------------------------------------------------
    # Banners & status
    # ------------------------------------------------------------------

    def banner(self, model: str, base_url: str, workspace: str) -> None:
        title = Text()
        title.append("OpenCodeHarness", style="bold cyan")
        title.append("  ·  model-agnostic agentic CLI", style="dim")
        body = Text.from_markup(
            f"[bold]model[/]     {model}\n"
            f"[bold]endpoint[/]  {base_url}\n"
            f"[bold]workspace[/] {workspace}\n\n"
            "[dim]Commands: /help  /model <name>  /reset  /tools  /config  /exit[/]"
        )
        self.console.print(Panel(body, title=title, border_style="cyan", padding=(1, 2)))

    def info(self, msg: str) -> None:
        self.console.print(f"[cyan]ℹ[/] {msg}")

    def warn(self, msg: str) -> None:
        self.console.print(f"[yellow]⚠[/] {msg}")

    def error(self, msg: str) -> None:
        self.console.print(f"[bold red]✖ {msg}[/]")

    def status(self, msg: str) -> None:
        self.console.print(f"[dim]… {msg}[/]")

    # ------------------------------------------------------------------
    # Spinner (model / shell wait)
    # ------------------------------------------------------------------

    def spinner_start(self, message: str = "Working…") -> None:
        self.spinner_stop()
        spinner = Spinner("dots", text=Text(message, style="cyan"))
        self._live = Live(spinner, console=self.console, refresh_per_second=12, transient=True)
        self._live.start()

    def spinner_update(self, message: str) -> None:
        if self._live is not None:
            self._live.update(Spinner("dots", text=Text(message, style="cyan")))

    def spinner_stop(self) -> None:
        if self._live is not None:
            try:
                self._live.stop()
            except Exception:  # pragma: no cover
                pass
            self._live = None

    # ------------------------------------------------------------------
    # Tool rendering
    # ------------------------------------------------------------------

    def tool_start(self, tc: ToolCall, args: dict[str, Any]) -> None:
        self.spinner_stop()
        name = tc.function.name
        title = f"⚙ tool · {name}"
        if self.show_tool_args and args:
            # Pretty-print args; for bash, highlight the command line
            if name == "execute_bash_command" and "command" in args:
                body: Any = Group(
                    Text("command:", style="bold yellow"),
                    Syntax(
                        str(args["command"]),
                        "bash",
                        theme=self.syntax_theme,
                        word_wrap=True,
                        line_numbers=False,
                    ),
                )
            elif name == "write_workspace_file":
                path = args.get("path", "?")
                content = str(args.get("content", ""))
                preview = content if len(content) <= 2000 else content[:2000] + "\n… [preview truncated]"
                lang = _guess_lang(str(path))
                body = Group(
                    Text(f"path: {path}", style="bold"),
                    Syntax(preview, lang, theme=self.syntax_theme, line_numbers=False, word_wrap=True),
                )
            else:
                pretty = json.dumps(args, indent=2, ensure_ascii=False)
                body = Syntax(pretty, "json", theme=self.syntax_theme, word_wrap=True)
        else:
            body = Text(f"id={tc.id}", style="dim")

        self.console.print(Panel(body, title=title, border_style="blue", title_align="left"))

    def tool_end(self, tc: ToolCall, result: str) -> None:
        self.spinner_stop()
        name = tc.function.name
        display = result if len(result) <= 6000 else result[:6000] + "\n… [output truncated for display]"
        style = "red" if display.startswith(("ERROR", "BLOCKED", "TIMEOUT")) else "green"

        if name == "execute_bash_command":
            renderable: Any = Syntax(display, "bash", theme=self.syntax_theme, word_wrap=True, line_numbers=False)
        elif name == "view_workspace_file" and "---\n" in display:
            header, _, file_body = display.partition("---\n")
            path_line = header.splitlines()[0] if header else ""
            lang = _guess_lang(path_line)
            renderable = Group(
                Text(header.rstrip(), style="dim"),
                Syntax(file_body, lang, theme=self.syntax_theme, line_numbers=True, word_wrap=True),
            )
        else:
            renderable = Text(display)

        self.console.print(
            Panel(
                renderable,
                title=f"↳ result · {name}",
                border_style=style,
                title_align="left",
            )
        )

    def assistant_final(self, text: str) -> None:
        self.spinner_stop()
        self.console.print(
            Panel(
                Markdown(text),
                title="✦ assistant",
                border_style="green",
                title_align="left",
                padding=(1, 2),
            )
        )

    def confirm_destructive(self, command: str, reason: str) -> bool:
        """
        Blocking [Y/n] confirmation for destructive shell commands.

        Returns True only on explicit yes (y/Y/yes). Default is No.
        """
        self.spinner_stop()
        self.console.print(
            Panel(
                Group(
                    Text("Potentially destructive command intercepted", style="bold red"),
                    Text(f"Reason: {reason}", style="yellow"),
                    Syntax(command, "bash", theme=self.syntax_theme, word_wrap=True),
                ),
                title="⚠ safety gate",
                border_style="red",
            )
        )
        try:
            answer = self.console.input("[bold red]Execute this command? [y/N][/] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            self.console.print()
            return False
        return answer in {"y", "yes"}


def _guess_lang(path_hint: str) -> str:
    lower = path_hint.lower()
    mapping = {
        ".py": "python",
        ".js": "javascript",
        ".ts": "typescript",
        ".tsx": "tsx",
        ".jsx": "jsx",
        ".json": "json",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".md": "markdown",
        ".sh": "bash",
        ".toml": "toml",
        ".rs": "rust",
        ".go": "go",
        ".html": "html",
        ".css": "css",
        ".sql": "sql",
    }
    for ext, lang in mapping.items():
        if ext in lower:
            return lang
    return "text"
