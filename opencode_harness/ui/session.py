"""
Honey interactive session — Claude Code / OpenCode terminal feel.

Feel targets:
  • Scrollback chat (no alt-screen takeover)
  • Compact tool tree:  ⏺ Tool(detail)  /  ⎿  summary + clipped body
  • Transient thinking spinner (dim, disappears cleanly)
  • Quiet assistant markdown (no loud banners)
  • prompt_toolkit input with soft prompt chrome
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Optional

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.styles import Style as PTStyle
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.padding import Padding
from rich.syntax import Syntax
from rich.text import Text

from opencode_harness import __version__
from opencode_harness.agent.loop import AgentLoop
from opencode_harness.config import DEFAULT_CONFIG_DIR, AppConfig
from opencode_harness.logging_setup import get_logger, log_path
from opencode_harness.models import ToolCall
from opencode_harness.provider.client import OpenAICompatibleClient, ProviderError
from opencode_harness.tools.registry import ToolRegistry
from opencode_harness.ui import art
from opencode_harness.ui.art import (
    C_CORAL,
    C_DIM,
    C_FOG,
    C_HONEY,
    C_MINT,
    C_SOFT,
)
from opencode_harness.ui.theme import (
    RainbowWait,
    complete_flash,
    get_theme,
    list_themes,
    rainbow_text,
)

log = get_logger("session")

# How many result lines to show before collapsing (Claude-like density)
_RESULT_PREVIEW_LINES = 12
_RESULT_MAX_CHARS = 2400


class SessionUI:
    """Claude/OpenCode conversation surface with rainbow wait chrome."""

    def __init__(
        self,
        console: Optional[Console] = None,
        *,
        syntax_theme: str = "monokai",
        theme_name: str = "rainbow",
    ):
        self.console = console or Console(highlight=False)
        self.syntax_theme = syntax_theme
        self.theme = get_theme(theme_name)
        self._live: Optional[Live] = None
        self._wait: Optional[RainbowWait] = None
        self._status = "idle"
        self._t0: Optional[float] = None
        self._turn_t0: Optional[float] = None
        self._tools_this_turn = 0
        self._streaming = False

    def set_theme(self, name: str) -> None:
        self.theme = get_theme(name)

    def prompt_style(self) -> PTStyle:
        return PTStyle.from_dict(
            {
                "prompt": f"bold {self.theme.prompt_color}",
                "rprompt": f"{self.theme.dim_color}",
            }
        )

    # ------------------------------------------------------------------
    # Chrome
    # ------------------------------------------------------------------

    def splash(
        self,
        *,
        model: str,
        base_url: str,
        workspace: str,
        auth: str,
        full: bool = False,
    ) -> None:
        art.print_splash(
            self.console,
            model=model,
            base_url=base_url,
            workspace=workspace,
            auth=auth,
            version=__version__,
            log_file=str(log_path()),
            full=full,
        )
        # Theme badge under splash
        badge = Text("  theme ")
        badge.append_text(rainbow_text(self.theme.name, self.theme.palette))
        badge.append(f"  ·  /theme to switch", style=self.theme.dim_color)
        self.console.print(badge)
        self.console.print()

    def turn_break(self) -> None:
        self.console.print()

    def info(self, msg: str) -> None:
        self.console.print(Text(f"  {art.ICON_DOT} {msg}", style=C_FOG))

    def warn(self, msg: str) -> None:
        self.console.print(Text(f"  ⚠ {msg}", style=C_HONEY))

    def error(self, msg: str) -> None:
        self.console.print(Text(f"  {art.ICON_FAIL} {msg}", style=self.theme.err_color))

    def system(self, msg: str) -> None:
        self.console.print(Text(f"  {msg}", style=self.theme.dim_color))

    # ------------------------------------------------------------------
    # Rainbow wait / loading (transient)
    # ------------------------------------------------------------------

    def think_start(self, message: str = "Thinking") -> None:
        self.think_stop()
        self._status = message
        self._t0 = time.monotonic()
        label = _humanize_status(message)
        self._wait = RainbowWait(label, theme=self.theme, t0=self._t0)
        self._live = Live(
            self._wait,
            console=self.console,
            refresh_per_second=18,
            transient=True,
            vertical_overflow="ellipsis",
        )
        self._live.start()

    def think_update(self, message: str) -> None:
        self._status = message
        if self._live is None or self._wait is None:
            self.think_start(message)
            return
        self._wait.set_label(_humanize_status(message))
        self._live.update(self._wait)

    def think_stop(self) -> None:
        if self._live is not None:
            try:
                self._live.stop()
            except Exception:  # pragma: no cover
                pass
            self._live = None
        self._wait = None
        self._t0 = None

    # ------------------------------------------------------------------
    # Conversation
    # ------------------------------------------------------------------

    def user_turn_spacer(self) -> None:
        """Gap after prompt_toolkit echo — never re-print the user text."""
        self._turn_t0 = time.monotonic()
        self._tools_this_turn = 0
        self._streaming = False
        # single blank line only
        self.console.print()

    def tool_start(self, tc: ToolCall, args: dict[str, Any]) -> None:
        self.think_stop()
        self._tools_this_turn += 1
        name = tc.function.name
        pretty = art._pretty_tool_name(name)
        detail = _tool_detail(name, args)

        # Rainbow tool bullet
        line = Text("  ")
        line.append(art.ICON_TOOL, style=self.theme.palette[self._tools_this_turn % len(self.theme.palette)])
        line.append(" ", style="")
        line.append(pretty, style=f"bold {self.theme.ink_color}")
        if detail:
            short = detail if len(detail) <= 72 else detail[:69] + "…"
            line.append("(", style=C_SOFT)
            line.append(short, style=C_FOG)
            line.append(")", style=C_SOFT)
        self.console.print(line)

        # Optional compact extras (edit diffs, write path only — not full body)
        if name == "edit_file":
            old = str(args.get("old_string", "")).splitlines()
            new = str(args.get("new_string", "")).splitlines()
            old_s = (old[0][:70] + "…") if old else ""
            new_s = (new[0][:70] + "…") if new else ""
            if old_s:
                self.console.print(Text(f"    − {old_s}", style=C_CORAL))
            if new_s:
                self.console.print(Text(f"    + {new_s}", style=C_MINT))

        self.think_start(f"Running {pretty}")

    def tool_end(self, tc: ToolCall, result: str) -> None:
        self.think_stop()
        name = tc.function.name
        ok = not result.startswith(("ERROR", "BLOCKED", "TIMEOUT"))
        summary = _result_summary(name, result, ok=ok)
        self.console.print(art.tool_result_prefix(ok=ok, summary=summary))

        # Collapsed body — first N lines, dim, tree-indented
        body_lines = _clip_result_lines(result)
        style = C_DIM if ok else C_CORAL
        for line in body_lines:
            # keep tree alignment under ⎿
            self.console.print(Text(f"     {line}", style=style))

    def assistant_final(self, text: str) -> None:
        self.think_stop()
        if self._streaming:
            # stream path already printed tokens
            self.console.print()
            self._streaming = False
        else:
            self.console.print(art.agent_header())
            md = Markdown(text or "")
            self.console.print(Padding(md, (0, 0, 0, 2)))
        self._print_turn_footer()

    def stream_delta(self, chunk: str) -> None:
        self.think_stop()
        if not self._streaming:
            self._streaming = True
            self.console.print(art.agent_header(), end="")
            self.console.print("  ", end="")
        self.console.print(chunk, end="", highlight=False, soft_wrap=True)

    def _print_turn_footer(self) -> None:
        if self._turn_t0 is None:
            return
        elapsed = time.monotonic() - self._turn_t0
        parts = []
        if self._tools_this_turn:
            parts.append(f"{self._tools_this_turn} tool" + ("s" if self._tools_this_turn != 1 else ""))
        parts.append(f"{elapsed:.1f}s")
        # Mini rainbow flash + stats
        self.console.print(complete_flash(self.theme, width=16), end="")
        self.console.print(Text("  " + " · ".join(parts), style=self.theme.dim_color))
        self._turn_t0 = None

    def confirm_destructive(self, command: str, reason: str) -> bool:
        self.think_stop()
        self.console.print()
        t = Text()
        t.append("  ⚠ ", style=f"bold {C_CORAL}")
        t.append("permission", style=f"bold {C_CORAL}")
        t.append(f"  {reason}", style=C_HONEY)
        self.console.print(t)
        self.console.print(
            Syntax(
                command,
                "bash",
                theme=self.syntax_theme,
                word_wrap=True,
                line_numbers=False,
                background_color="default",
            )
        )
        try:
            answer = self.console.input(
                f"  [{C_CORAL}]allow?[/] [dim]\\[y/N][/] "
            ).strip().lower()
        except (EOFError, KeyboardInterrupt):
            self.console.print()
            return False
        return answer in {"y", "yes"}


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _humanize_status(message: str) -> str:
    m = (message or "").strip().rstrip("…").strip()
    low = m.lower()
    if "consult" in low or "model" in low:
        return f"{art.ICON_THINK} Thinking"
    if "running" in low:
        return m if m.startswith(art.ICON_THINK) else f"{art.ICON_THINK} {m}"
    if not m:
        return f"{art.ICON_THINK} Working"
    if not m.startswith(art.ICON_THINK):
        return f"{art.ICON_THINK} {m[0].upper() + m[1:]}" if m else f"{art.ICON_THINK} Working"
    return m


def _tool_detail(name: str, args: dict[str, Any]) -> str:
    if name == "execute_bash_command":
        return str(args.get("command", "")).replace("\n", " ")
    if name in {"read_file", "view_workspace_file", "write_file", "write_workspace_file", "edit_file", "list_directory"}:
        path = str(args.get("path", "."))
        if name == "read_file" and (args.get("offset") or args.get("limit")):
            return f"{path}:{args.get('offset', 1)}"
        return path
    if name == "glob_files":
        return str(args.get("pattern", ""))
    if name == "grep_search":
        return str(args.get("pattern", ""))
    if name == "browse_web_content":
        return str(args.get("url", ""))
    return ""


def _result_summary(name: str, result: str, *, ok: bool) -> str:
    if not ok:
        head = result.splitlines()[0] if result else "failed"
        return head[:100]
    lines = result.splitlines() if result else []
    n = len(lines)
    if name == "execute_bash_command":
        code = "?"
        for ln in lines[:5]:
            if ln.startswith("exit_code:"):
                code = ln.split(":", 1)[-1].strip()
                break
        return f"exit {code} · {n} lines"
    if name in {"read_file", "view_workspace_file"}:
        return f"read · {n} lines"
    if name in {"write_file", "write_workspace_file", "edit_file"}:
        # first line is OK: …
        first = lines[0] if lines else "done"
        return first if first.startswith("OK") else f"wrote · {n} lines"
    if name in {"glob_files", "grep_search", "list_directory"}:
        return f"{n} lines"
    if name == "browse_web_content":
        return f"fetched · {n} lines"
    return f"done · {n} lines"


def _clip_result_lines(result: str) -> list[str]:
    if not result:
        return []
    # Drop noisy headers for bash (keep stdout body denser)
    lines = result.splitlines()
    cleaned: list[str] = []
    skip_prefixes = ("--- stdout ---", "--- stderr ---")
    for ln in lines:
        if ln in skip_prefixes:
            continue
        if ln == "(empty)":
            continue
        cleaned.append(ln)

    # Cap chars then lines
    text = "\n".join(cleaned)
    if len(text) > _RESULT_MAX_CHARS:
        text = text[:_RESULT_MAX_CHARS]
        cleaned = text.splitlines()
        cleaned.append("…")

    if len(cleaned) > _RESULT_PREVIEW_LINES:
        head = cleaned[:_RESULT_PREVIEW_LINES]
        more = len(cleaned) - _RESULT_PREVIEW_LINES
        head.append(f"… +{more} lines")
        return head
    return cleaned


def _guess_lang(path: str) -> str:
    lower = path.lower()
    for ext, lang in {
        ".py": "python",
        ".js": "javascript",
        ".ts": "typescript",
        ".json": "json",
        ".md": "markdown",
        ".sh": "bash",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".rs": "rust",
        ".go": "go",
    }.items():
        if lower.endswith(ext):
            return lang
    return "text"


# ---------------------------------------------------------------------------
# Slash commands + main loop
# ---------------------------------------------------------------------------

def _handle_slash(
    line: str,
    loop: AgentLoop,
    ui: SessionUI,
    config: AppConfig,
) -> bool:
    parts = line.strip().split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    if cmd in {"/exit", "/quit", "/q"}:
        ui.console.print(art.goodbye_art())
        raise SystemExit(0)

    if cmd == "/help":
        ui.system("commands")
        for row in (
            "/model [name]   pick model (sectioned list if no name)",
            "/models         same as /model",
            "/theme [name]   rainbow · prism · pulse · honey · quiet",
            "/tools          list tools",
            "/mode build|plan",
            "/reset          clear conversation",
            "/config         show settings",
            "/logs           activity log path",
            "/workspace [p]  show/set workspace",
            "/banner         big splash art",
            "/exit",
        ):
            ui.system(f"  {row}")
        return True

    if cmd in {"/theme", "/themes"}:
        if not arg:
            ui.system(f"current theme · {ui.theme.name}")
            for th in list_themes():
                mark = "→" if th.name == ui.theme.name else " "
                ui.system(f"  {mark} {th.name:8}  {th.description}")
            ui.system("  set with /theme rainbow")
            return True
        name = arg.strip().lower()
        if name not in {t.name for t in list_themes()}:
            ui.warn(f"unknown theme {name!r}  ·  try /theme")
            return True
        ui.set_theme(name)
        config.ui.theme = name
        ui.info(f"theme → {name}")
        # Quick demo of the wait animation
        ui.think_start("Theme preview")
        time.sleep(0.9)
        ui.think_stop()
        return True

    if cmd == "/banner":
        ui.splash(
            model=config.provider.model,
            base_url=config.provider.base_url,
            workspace=str(config.workspace),
            auth="",
            full=True,
        )
        return True

    if cmd == "/mode":
        if not arg:
            ui.info(f"mode {getattr(config, 'agent_mode', 'build')}")
        elif arg.lower() in {"build", "plan"}:
            config.agent_mode = arg.lower()
            loop.registry.set_mode(arg.lower())  # type: ignore[arg-type]
            loop.reset()
            ui.info(f"mode → {arg.lower()}  (history cleared)")
        else:
            ui.warn("mode must be build or plan")
        return True

    if cmd in {"/model", "/models"}:
        if arg:
            loop.set_model(arg)
            ui.info(f"model → {arg}")
            return True
        from opencode_harness.ui.picker import pick_model

        chosen = pick_model(
            ui.console,
            current=config.provider.model,
            configured=list(config.provider.models or []),
        )
        if not chosen:
            ui.system("unchanged")
            return True
        if chosen == config.provider.model:
            ui.info(f"already on {chosen}")
            return True
        loop.set_model(chosen)
        if chosen not in config.provider.models:
            config.provider.models = list(config.provider.models) + [chosen]
        ui.info(f"model → {chosen}")
        return True

    if cmd == "/tools":
        for name in loop.registry.list_names():
            ui.system(f"  {art._pretty_tool_name(name):8}  {name}")
        return True

    if cmd == "/reset":
        loop.reset()
        ui.info("conversation cleared")
        return True

    if cmd == "/config":
        ui.system(f"endpoint   {config.provider.base_url}")
        ui.system(f"model      {config.provider.model}")
        ui.system(f"mode       {getattr(config, 'agent_mode', 'build')}")
        ui.system(f"workspace  {config.workspace}")
        ui.system(f"log        {log_path()}")
        return True

    if cmd in {"/logs", "/log"}:
        from opencode_harness.logging_setup import recent_activity

        ui.info(f"log → {log_path()}")
        for row in recent_activity(10):
            ui.system(row)
        return True

    if cmd == "/workspace":
        if not arg:
            ui.info(f"workspace → {config.workspace}")
        else:
            new_ws = Path(arg).expanduser().resolve()
            if not new_ws.is_dir():
                ui.error(f"not a directory: {new_ws}")
            else:
                config.workspace = new_ws
                loop.registry.workspace = new_ws
                loop.reset()
                ui.info(f"workspace → {new_ws}")
        return True

    ui.warn(f"unknown {cmd}  ·  /help")
    return True


def create_session_loop(config: AppConfig, ui: SessionUI, api_key: str) -> AgentLoop:
    client = OpenAICompatibleClient(config.provider, api_key=api_key)

    mode = getattr(config, "agent_mode", "build") or "build"
    registry = ToolRegistry(
        workspace=config.workspace,
        tool_config=config.tools,
        confirm_destructive=ui.confirm_destructive,
        mode=mode if mode in ("build", "plan") else "build",  # type: ignore[arg-type]
    )

    def on_status(msg: str) -> None:
        ui.think_update(msg)

    def on_tool_start(tc: ToolCall, args: dict[str, Any]) -> None:
        ui.tool_start(tc, args)

    def on_tool_end(tc: ToolCall, result: str) -> None:
        ui.tool_end(tc, result)

    def on_assistant_text(text: str) -> None:
        ui.assistant_final(text)

    def on_stream_delta(chunk: str) -> None:
        ui.stream_delta(chunk)

    return AgentLoop(
        config=config,
        client=client,
        registry=registry,
        on_tool_start=on_tool_start,
        on_tool_end=on_tool_end,
        on_assistant_text=on_assistant_text,
        on_status=on_status,
        on_stream_delta=on_stream_delta,
    )


def _build_key_bindings() -> KeyBindings:
    """Escape clears; keep Enter as submit (Claude-like single-line default)."""
    kb = KeyBindings()

    @kb.add(Keys.Escape)
    def _(event) -> None:  # type: ignore[no-untyped-def]
        event.app.current_buffer.reset()

    return kb


def run_session(
    config: AppConfig,
    *,
    api_key: str,
    auth_label: str = "signed in",
) -> int:
    """Main interactive experience. Returns process exit code."""
    theme_name = getattr(config.ui, "theme", "rainbow") or "rainbow"
    ui = SessionUI(syntax_theme=config.ui.syntax_theme, theme_name=theme_name)
    loop = create_session_loop(config, ui, api_key)

    history_path = DEFAULT_CONFIG_DIR / "history"
    DEFAULT_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    # Right-side hint (model) — OpenCode-ish chrome without noise
    def rprompt() -> HTML:
        m = config.provider.model
        if len(m) > 18:
            m = m[:16] + "…"
        return HTML(f'<rprompt>{m}</rprompt>')

    session: PromptSession[str] = PromptSession(
        history=FileHistory(str(history_path)),
        style=ui.prompt_style(),
        enable_history_search=True,
        key_bindings=_build_key_bindings(),
        rprompt=rprompt,
        multiline=False,
    )

    ui.splash(
        model=config.provider.model,
        base_url=config.provider.base_url,
        workspace=str(config.workspace),
        auth=auth_label,
        full=True,
    )
    log.info("session started (claude/opencode-style)")

    try:
        while True:
            try:
                line = session.prompt(
                    HTML(f"<prompt>{art.ICON_USER}</prompt> "),
                )
            except KeyboardInterrupt:
                # Claude-like: Ctrl+C clears the line, doesn't kill the session
                ui.console.print()
                continue
            except EOFError:
                ui.console.print()
                ui.console.print(art.goodbye_art())
                return 0

            line = line.strip()
            if not line:
                continue

            if line.startswith("/"):
                try:
                    _handle_slash(line, loop, ui, config)
                except SystemExit as e:
                    return int(e.code or 0)
                continue

            ui.user_turn_spacer()
            ui.think_start("Thinking")
            try:
                result = loop.run(line)
                ui.think_stop()
                # Stream path skips on_assistant_text — close the stream + footer
                if ui._streaming:
                    ui.assistant_final(result.final_text or "")
                elif result.stopped_reason == "circuit_breaker":
                    # may already have been shown via on_assistant_text
                    if ui._turn_t0 is not None:
                        ui._print_turn_footer()
                elif result.stopped_reason == "completed" and ui._turn_t0 is not None:
                    # no final text callback fired
                    ui._print_turn_footer()
                ui.turn_break()
            except ProviderError as exc:
                ui.think_stop()
                ui.error(str(exc))
                log.error("provider error: %s", exc)
            except KeyboardInterrupt:
                ui.think_stop()
                ui.warn("interrupted")
            except Exception as exc:  # noqa: BLE001
                ui.think_stop()
                ui.error(f"{type(exc).__name__}: {exc}")
                log.exception("session error")
    finally:
        loop.client.close()
        log.info("session closed")
