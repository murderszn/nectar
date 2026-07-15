"""
Full-screen terminal UI — OpenCode / Mimo Code style.

Layout (Textual app, alt-screen):

  ┌─ header: brand · model · workspace · auth ──────────────────────┐
  │  scrollable conversation log (user / tool / assistant / system)  │
  ├─ status bar ─────────────────────────────────────────────────────┤
  │  input dock  (Enter submit · Esc cancel busy · Ctrl+C quit)      │
  └──────────────────────────────────────────────────────────────────┘

The agent loop runs on a worker thread; UI updates are marshalled via
`App.call_from_thread` so the main event loop stays responsive.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Optional

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import Footer, Input, Label, Markdown, Static

from opencode_harness import __version__
from opencode_harness.agent.loop import AgentLoop
from opencode_harness.config import AppConfig
from opencode_harness.logging_setup import (
    add_activity_listener,
    get_logger,
    log_path,
    remove_activity_listener,
)
from opencode_harness.models import ToolCall
from opencode_harness.provider.client import OpenAICompatibleClient, ProviderError
from opencode_harness.tools.registry import ToolRegistry

log = get_logger("tui")


# ---------------------------------------------------------------------------
# Log entry widgets
# ---------------------------------------------------------------------------

class UserBubble(Static):
    DEFAULT_CSS = """
    UserBubble {
        background: #1a2f3a;
        color: #e0f0ff;
        border: tall #2a6f8f;
        padding: 0 1;
        margin: 1 2 0 8;
    }
    """

    def __init__(self, text: str) -> None:
        super().__init__(text)
        self.border_title = "you"


class AssistantBubble(Static):
    DEFAULT_CSS = """
    AssistantBubble {
        background: #15251c;
        color: #d8f5e0;
        border: tall #2d8a57;
        padding: 0 1;
        margin: 1 8 0 2;
    }
    """

    def __init__(self, text: str) -> None:
        # Prefer markdown rendering for assistant prose
        super().__init__()
        self._text = text
        self.border_title = "assistant"

    def compose(self) -> ComposeResult:
        yield Markdown(self._text)


class ToolBubble(Static):
    DEFAULT_CSS = """
    ToolBubble {
        background: #1c1c28;
        color: #c8c8e0;
        border: tall #4a4a8a;
        padding: 0 1;
        margin: 1 4 0 4;
        max-height: 18;
        overflow-y: auto;
    }
    ToolBubble.-error {
        border: tall #a04040;
        background: #2a1515;
    }
    """

    def __init__(self, title: str, body: str, *, error: bool = False) -> None:
        super().__init__(body)
        self.border_title = title
        if error:
            self.add_class("-error")


class SystemNote(Static):
    DEFAULT_CSS = """
    SystemNote {
        color: #7a8a9a;
        text-align: center;
        margin: 1 2;
    }
    """


# ---------------------------------------------------------------------------
# Destructive-command confirmation modal
# ---------------------------------------------------------------------------

class ConfirmDestructive(ModalScreen[bool]):
    """Blocking [Y/n] style modal for the safety gate."""

    DEFAULT_CSS = """
    ConfirmDestructive {
        align: center middle;
    }
    ConfirmDestructive > Vertical {
        width: 72;
        max-width: 90%;
        height: auto;
        max-height: 80%;
        background: #2a1212;
        border: thick #c04040;
        padding: 1 2;
    }
    ConfirmDestructive .title {
        color: #ff8080;
        text-style: bold;
        margin-bottom: 1;
    }
    ConfirmDestructive .cmd {
        background: #1a0a0a;
        color: #ffd0d0;
        padding: 1;
        margin: 1 0;
    }
    ConfirmDestructive .hint {
        color: #aaa;
        margin-top: 1;
    }
    """

    BINDINGS = [
        Binding("y", "yes", "Yes", show=True),
        Binding("n", "no", "No", show=True),
        Binding("escape", "no", "Cancel", show=False),
    ]

    def __init__(self, command: str, reason: str) -> None:
        super().__init__()
        self.command = command
        self.reason = reason

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("⚠  Potentially destructive command", classes="title")
            yield Label(f"Reason: {self.reason}")
            yield Static(self.command, classes="cmd")
            yield Label("Execute?  [Y]es  /  [N]o", classes="hint")

    def action_yes(self) -> None:
        self.dismiss(True)

    def action_no(self) -> None:
        self.dismiss(False)


# ---------------------------------------------------------------------------
# Main full-screen app
# ---------------------------------------------------------------------------

class OpenCodeHarnessApp(App[None]):
    """Fullscreen agent shell — default experience for `opencode-harness`."""

    TITLE = "OpenCodeHarness"
    CSS = """
    Screen {
        background: #0d1117;
    }

    #header {
        dock: top;
        height: 3;
        background: #0b1220;
        color: #c9d1d9;
        padding: 0 2;
        border-bottom: solid #1f6feb;
    }
    #header Horizontal {
        height: 100%;
        align: left middle;
    }
    #brand {
        color: #58a6ff;
        text-style: bold;
        width: auto;
        margin-right: 2;
    }
    #meta {
        color: #8b949e;
        width: 1fr;
    }
    #auth-badge {
        color: #3fb950;
        width: auto;
        text-align: right;
    }

    #log {
        height: 1fr;
        padding: 0 1;
        scrollbar-color: #30363d;
        scrollbar-background: #0d1117;
    }

    #activity {
        dock: bottom;
        height: 4;
        background: #0a0e14;
        color: #6e7681;
        padding: 0 1;
        border-top: solid #21262d;
        overflow-y: hidden;
    }
    #activity.-busy {
        color: #79c0ff;
        border-top: solid #1f6feb;
    }

    #status {
        dock: bottom;
        height: 1;
        background: #161b22;
        color: #8b949e;
        padding: 0 2;
        border-top: solid #21262d;
    }
    #status.-busy {
        color: #58a6ff;
        text-style: bold;
    }

    #input-dock {
        dock: bottom;
        height: 3;
        background: #0b1220;
        padding: 0 1;
        border-top: solid #1f6feb;
    }
    #prompt {
        width: 1fr;
        background: #0d1117;
        border: tall #30363d;
        padding: 0 1;
    }
    #prompt:focus {
        border: tall #58a6ff;
    }

    Footer {
        background: #010409;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit_app", "Quit", show=True, priority=True),
        Binding("ctrl+d", "quit_app", "Quit", show=False),
        Binding("ctrl+l", "clear_log", "Clear", show=True),
        Binding("f1", "show_help", "Help", show=True),
        Binding("escape", "cancel_busy", "Cancel", show=False),
    ]

    status_text: reactive[str] = reactive("ready")
    busy: reactive[bool] = reactive(False)

    def __init__(
        self,
        config: AppConfig,
        *,
        api_key: str,
        auth_label: str = "signed in",
    ) -> None:
        super().__init__()
        self.config = config
        self.api_key = api_key
        self.auth_label = auth_label
        self._client: Optional[OpenAICompatibleClient] = None
        self._loop: Optional[AgentLoop] = None
        self._worker_thread: Optional[threading.Thread] = None
        self._confirm_event = threading.Event()
        self._confirm_result = False
        self._stream_buffer = ""
        self._activity_lines: list[str] = []
        self._busy_started: Optional[float] = None
        self._status_base = "ready"

    # ------------------------------------------------------------------
    # Compose
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Horizontal(id="header"):
            yield Label("◆ OpenCodeHarness", id="brand")
            yield Label(self._meta_line(), id="meta")
            yield Label(self.auth_label, id="auth-badge")

        yield VerticalScroll(id="log")
        # Live activity feed — last few logger lines so you can see it's alive
        yield Static("activity · waiting…", id="activity")
        yield Static("ready · type a goal and press Enter", id="status")

        with Horizontal(id="input-dock"):
            yield Input(
                placeholder="Describe a goal…  (/help  /model  /reset  /logs  /quit)",
                id="prompt",
            )

        yield Footer()

    def _meta_line(self) -> str:
        ws = str(self.config.workspace)
        if len(ws) > 48:
            ws = "…" + ws[-46:]
        return (
            f"v{__version__}  ·  model [b]{self.config.provider.model}[/b]  ·  "
            f"{self.config.provider.base_url}  ·  {ws}"
        )

    def on_mount(self) -> None:
        add_activity_listener(self._on_activity_event)
        self.set_interval(1.0, self._tick_heartbeat)

        self._client = OpenAICompatibleClient(self.config.provider, api_key=self.api_key)
        mode = getattr(self.config, "agent_mode", "build") or "build"
        registry = ToolRegistry(
            workspace=self.config.workspace,
            tool_config=self.config.tools,
            confirm_destructive=self._confirm_destructive_sync,
            mode=mode if mode in ("build", "plan") else "build",  # type: ignore[arg-type]
        )
        self._loop = AgentLoop(
            config=self.config,
            client=self._client,
            registry=registry,
            on_tool_start=self._on_tool_start,
            on_tool_end=self._on_tool_end,
            on_assistant_text=self._on_assistant_text,
            on_status=self._on_status,
            on_stream_delta=self._on_stream_delta,
        )
        self.query_one("#prompt", Input).focus()
        log.info("TUI session started  workspace=%s  model=%s", self.config.workspace, self.config.provider.model)
        self._append_system(
            f"Full-screen session ready. Workspace: {self.config.workspace}\n"
            f"Tools: {', '.join(registry.list_names())}\n"
            f"Activity log: {log_path()}\n"
            "Type a high-level goal, or /help for commands. "
            "Watch the activity strip below while tools run."
        )
        self._push_activity("INFO", f"session ready · log → {log_path()}")

    def on_unmount(self) -> None:
        remove_activity_listener(self._on_activity_event)
        if self._client:
            self._client.close()
        log.info("TUI session closed")

    # ------------------------------------------------------------------
    # Reactive status
    # ------------------------------------------------------------------

    def watch_status_text(self, value: str) -> None:
        try:
            bar = self.query_one("#status", Static)
            bar.update(value)
            bar.set_class(self.busy, "-busy")
        except Exception:  # pragma: no cover
            pass

    def watch_busy(self, value: bool) -> None:
        try:
            prompt = self.query_one("#prompt", Input)
            prompt.disabled = value
            bar = self.query_one("#status", Static)
            bar.set_class(value, "-busy")
            act = self.query_one("#activity", Static)
            act.set_class(value, "-busy")
            if value:
                self._busy_started = time.monotonic()
            else:
                self._busy_started = None
        except Exception:  # pragma: no cover
            pass

    def _tick_heartbeat(self) -> None:
        """Refresh status with elapsed time so a hung API still looks alive."""
        if not self.busy or self._busy_started is None:
            return
        elapsed = int(time.monotonic() - self._busy_started)
        base = self._status_base or "working"
        # Don't clobber streaming previews that already include detail
        if base.startswith("streaming"):
            return
        self.status_text = f"⏳ {base}  ·  {elapsed}s elapsed"

    # ------------------------------------------------------------------
    # Log helpers (always call from UI thread)
    # ------------------------------------------------------------------

    def _log(self) -> VerticalScroll:
        return self.query_one("#log", VerticalScroll)

    def _append(self, widget: Static) -> None:
        log = self._log()
        log.mount(widget)
        log.scroll_end(animate=False)

    def _append_system(self, text: str) -> None:
        self._append(SystemNote(text))

    def _append_user(self, text: str) -> None:
        self._append(UserBubble(text))

    def _append_assistant(self, text: str) -> None:
        self._append(AssistantBubble(text))

    def _append_tool(self, title: str, body: str, *, error: bool = False) -> None:
        # Cap display size so a huge cat doesn't freeze the TUI
        display = body if len(body) <= 4000 else body[:4000] + "\n… [truncated]"
        self._append(ToolBubble(title, display, error=error))

    def _push_activity(self, level: str, message: str) -> None:
        """Update the bottom activity strip (UI thread)."""
        ts = time.strftime("%H:%M:%S")
        line = f"{ts}  {level:<5}  {message}"
        self._activity_lines.append(line)
        self._activity_lines = self._activity_lines[-6:]
        try:
            feed = self.query_one("#activity", Static)
            # Show last 3 lines so the strip feels live
            feed.update("\n".join(self._activity_lines[-3:]))
        except Exception:  # pragma: no cover
            pass

    def _on_activity_event(self, level: str, message: str) -> None:
        """Logger listener — may fire from any thread."""
        # Skip noisy debug in the strip; file still has everything
        if level == "DEBUG":
            return

        def apply() -> None:
            self._push_activity(level, message)

        try:
            self.call_from_thread(apply)
        except Exception:
            # Before mount / after unmount
            pass

    # ------------------------------------------------------------------
    # Agent callbacks (may run on worker thread → hop to UI thread)
    # ------------------------------------------------------------------

    def _ui(self, fn: Callable[[], None]) -> None:
        try:
            self.call_from_thread(fn)
        except Exception:
            # App may be shutting down
            pass

    def _on_status(self, msg: str) -> None:
        def apply() -> None:
            self._status_base = msg
            self.status_text = msg
            self.busy = True

        self._ui(apply)

    def _on_tool_start(self, tc: ToolCall, args: dict[str, Any]) -> None:
        name = tc.function.name
        if name == "execute_bash_command":
            preview = str(args.get("command", ""))
        elif name in {"view_workspace_file", "write_workspace_file"}:
            preview = str(args.get("path", ""))
        elif name == "browse_web_content":
            preview = str(args.get("url", ""))
        else:
            preview = str(args)[:200]

        def apply() -> None:
            self._status_base = f"⚙ running {name}"
            self.status_text = f"⚙ {name}…"
            self.busy = True
            self._append_tool(f"⚙ {name}", preview)

        self._ui(apply)

    def _on_tool_end(self, tc: ToolCall, result: str) -> None:
        err = result.startswith(("ERROR", "BLOCKED", "TIMEOUT"))

        def apply() -> None:
            self._append_tool(f"↳ {tc.function.name}", result, error=err)
            self._status_base = "tool finished · consulting model…"
            self.status_text = self._status_base

        self._ui(apply)

    def _on_assistant_text(self, text: str) -> None:
        def apply() -> None:
            self._stream_buffer = ""
            self._append_assistant(text)
            self._status_base = "ready"
            self.status_text = "ready"
            self.busy = False

        self._ui(apply)

    def _on_stream_delta(self, chunk: str) -> None:
        # Accumulate; flush as a single bubble on newline-heavy chunks or end
        self._stream_buffer += chunk

        def apply() -> None:
            # Live status preview of stream
            preview = self._stream_buffer.replace("\n", " ")
            if len(preview) > 80:
                preview = "…" + preview[-78:]
            self._status_base = f"streaming · {preview}"
            self.status_text = self._status_base

        self._ui(apply)

    def _confirm_destructive_sync(self, command: str, reason: str) -> bool:
        """
        Called from the tool worker thread. Blocks until the modal resolves.
        """
        self._confirm_event.clear()
        self._confirm_result = False

        def open_modal() -> None:
            def done(result: bool | None) -> None:
                self._confirm_result = bool(result)
                self._confirm_event.set()

            self.push_screen(ConfirmDestructive(command, reason), done)

        self._ui(open_modal)
        # Wait up to 10 minutes for the human
        self._confirm_event.wait(timeout=600)
        return self._confirm_result

    # ------------------------------------------------------------------
    # Input handling
    # ------------------------------------------------------------------

    @on(Input.Submitted, "#prompt")
    def handle_submit(self, event: Input.Submitted) -> None:
        text = (event.value or "").strip()
        event.input.value = ""
        if not text or self.busy:
            return

        if text.startswith("/"):
            self._handle_slash(text)
            return

        self._append_user(text)
        self.busy = True
        self.status_text = "consulting model…"
        self._stream_buffer = ""
        self._run_agent(text)

    def _run_agent(self, goal: str) -> None:
        assert self._loop is not None

        def worker() -> None:
            try:
                result = self._loop.run(goal)  # type: ignore[union-attr]

                def finish() -> None:
                    # Stream path skips on_assistant_text — materialize bubble here.
                    streamed = bool(self._stream_buffer.strip())
                    if result.stopped_reason == "completed" and streamed and result.final_text:
                        self._append_assistant(result.final_text)
                    self._stream_buffer = ""
                    self.busy = False
                    self._status_base = "ready"
                    self.status_text = (
                        f"ready · {result.tool_rounds} tool call(s) · {result.stopped_reason}"
                    )
                    log.info(
                        "turn finished  reason=%s  tools=%d",
                        result.stopped_reason,
                        result.tool_rounds,
                    )
                    try:
                        self.query_one("#prompt", Input).focus()
                    except Exception:
                        pass

                self.call_from_thread(finish)
            except ProviderError as exc:
                log.error("provider error in TUI worker: %s", exc)

                def fail() -> None:
                    self._append_system(f"Provider error: {exc}")
                    self.busy = False
                    self._status_base = "error"
                    self.status_text = "error"
                    self.query_one("#prompt", Input).focus()

                self.call_from_thread(fail)
            except Exception as exc:  # noqa: BLE001
                log.exception("unexpected error in TUI worker")

                def fail2() -> None:
                    self._append_system(f"Unexpected error: {type(exc).__name__}: {exc}")
                    self.busy = False
                    self._status_base = "error"
                    self.status_text = "error"
                    self.query_one("#prompt", Input).focus()

                self.call_from_thread(fail2)

        t = threading.Thread(target=worker, name="agent-loop", daemon=True)
        self._worker_thread = t
        t.start()

    def _handle_slash(self, line: str) -> None:
        parts = line.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        if cmd in {"/quit", "/exit", "/q"}:
            self.exit()
            return
        if cmd == "/help":
            self._append_system(
                "Commands:\n"
                "  /help              this help\n"
                "  /model [name]      show or switch model\n"
                "  /models            list configured models\n"
                "  /tools             list tools\n"
                "  /reset             clear conversation\n"
                "  /config            show settings\n"
                "  /logs              show activity log path + recent lines\n"
                "  /clear             clear the conversation view\n"
                "  /quit              exit full-screen session\n"
                "Keys: Enter submit · Ctrl+L clear · Ctrl+C quit · F1 help\n"
                f"File log: {log_path()}  (tail -f that path in another terminal)"
            )
            return
        if cmd in {"/logs", "/log"}:
            from opencode_harness.logging_setup import recent_activity

            recent = recent_activity(15)
            body = "\n".join(recent) if recent else "(no activity yet)"
            self._append_system(f"Log file: {log_path()}\n\nRecent activity:\n{body}")
            return
        if cmd == "/model":
            if not arg:
                self._append_system(f"Active model: {self.config.provider.model}")
            else:
                assert self._loop
                self._loop.set_model(arg)
                self.query_one("#meta", Label).update(self._meta_line())
                self._append_system(f"Switched model → {arg}")
            return
        if cmd == "/models":
            lines = []
            for m in self.config.provider.models:
                mark = "→" if m == self.config.provider.model else " "
                lines.append(f"  {mark} {m}")
            self._append_system("Models:\n" + "\n".join(lines))
            return
        if cmd == "/tools":
            assert self._loop
            names = self._loop.registry.list_names()
            self._append_system("Tools:\n" + "\n".join(f"  · {n}" for n in names))
            return
        if cmd == "/reset":
            assert self._loop
            self._loop.reset()
            self._append_system("Conversation history cleared.")
            return
        if cmd == "/config":
            self._append_system(
                f"base_url:   {self.config.provider.base_url}\n"
                f"model:      {self.config.provider.model}\n"
                f"workspace:  {self.config.workspace}\n"
                f"bash_timeout: {self.config.tools.bash_timeout}s\n"
                f"max_tool_rounds: {self.config.tools.max_tool_rounds}"
            )
            return
        if cmd == "/clear":
            self.action_clear_log()
            return
        self._append_system(f"Unknown command: {cmd}  (try /help)")

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_quit_app(self) -> None:
        self.exit()

    def action_clear_log(self) -> None:
        log = self._log()
        log.remove_children()
        self._append_system("Log cleared.")

    def action_show_help(self) -> None:
        self._handle_slash("/help")

    def action_cancel_busy(self) -> None:
        # Soft cancel: we can't kill the HTTP request mid-flight cleanly yet,
        # but we free the input if somehow stuck.
        if self.busy:
            self.status_text = "busy — wait for current step to finish"
        else:
            self.status_text = "ready"


def run_tui(config: AppConfig, *, api_key: str, auth_label: str = "signed in") -> int:
    """Launch the full-screen app; returns process exit code."""
    app = OpenCodeHarnessApp(config, api_key=api_key, auth_label=auth_label)
    app.run()
    return 0
