"""
Honey CLI entrypoint (OpenCodeHarness under the hood).

Primary command: ``honey``
Legacy aliases:  ``opencode-harness``, ``och``

Default interactive mode: Claude / OpenCode-style scrollback chat with
unique fluid ASCII art (not a full-screen alt buffer).

Auth mirrors Sprout: Pollinations BYOP device flow → credentials.json.

Commands:
  honey                 scrollback agent session (default)
  honey login           Pollen BYOP sign-in
  honey logout          clear stored key
  honey status          show auth + endpoint
  honey "goal…"         one-shot
  honey --tui           optional full-screen Textual mode
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style as PTStyle
from rich.console import Console

from opencode_harness import __version__
from opencode_harness.agent.loop import AgentLoop
from opencode_harness.auth.login import (
    is_interactive,
    perform_byop_login,
    perform_logout,
    require_api_key,
)
from opencode_harness.auth.store import (
    credentials_path,
    mask_key,
    resolve_api_key,
)
from opencode_harness.config import (
    DEFAULT_CONFIG_DIR,
    DEFAULT_CONFIG_PATH,
    AppConfig,
    ensure_default_config,
    load_config,
)
from opencode_harness.provider.client import OpenAICompatibleClient, ProviderError
from opencode_harness.tools.registry import ToolRegistry
from opencode_harness.ui.console import TerminalUI


PROMPT_STYLE = PTStyle.from_dict({"prompt": "ansicyan bold"})

# Primary interactive brand — argv[0] basename wins when installed as honey
PRIMARY_PROG = "honey"


def _prog_name() -> str:
    base = Path(sys.argv[0]).name if sys.argv else PRIMARY_PROG
    # python -m opencode_harness → still market as honey
    if base in {"__main__.py", "opencode_harness", "python", "python3"}:
        return PRIMARY_PROG
    if base in {"opencode-harness", "och", "honey"}:
        return base
    return PRIMARY_PROG


def build_parser() -> argparse.ArgumentParser:
    prog = _prog_name()
    p = argparse.ArgumentParser(
        prog=prog,
        description=(
            "Honey — open coding agent for the terminal "
            "(Pollen login · OpenCode-style tools)"
        ),
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument(
        "-c",
        "--config",
        type=Path,
        default=None,
        help=f"Path to config.yaml/json (default: {DEFAULT_CONFIG_PATH})",
    )
    p.add_argument(
        "-m",
        "--model",
        type=str,
        default=None,
        help="Override provider model (e.g. kimi, deepseek, hermes)",
    )
    p.add_argument(
        "-w",
        "--workspace",
        type=Path,
        default=None,
        help="Workspace root for file/bash tools (default: CWD)",
    )
    p.add_argument(
        "--base-url",
        type=str,
        default=None,
        help="Override OpenAI-compatible base URL",
    )
    p.add_argument(
        "--init",
        action="store_true",
        help="Write default config to ~/.opencode_harness/config.yaml and exit",
    )
    p.add_argument(
        "--tui",
        action="store_true",
        help="Use the experimental full-screen Textual UI instead of scrollback chat",
    )
    p.add_argument(
        "--classic",
        action="store_true",
        help=argparse.SUPPRESS,  # legacy alias → scrollback session
    )
    p.add_argument(
        "--no-tui",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    p.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Mirror activity logs to stderr (also enables DEBUG file detail)",
    )
    p.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Only log warnings/errors",
    )
    p.add_argument(
        "--log-file",
        type=Path,
        default=None,
        help="Override activity log path (default: ~/.opencode_harness/logs/harness.log)",
    )
    p.add_argument(
        "command_or_prompt",
        nargs="*",
        help="Subcommand (login|logout|status|logs) or a one-shot goal string",
    )
    return p


def _apply_overrides(config: AppConfig, args: argparse.Namespace) -> AppConfig:
    if args.model:
        config.provider.model = args.model
    if args.base_url:
        config.provider.base_url = args.base_url.rstrip("/")
    if args.workspace:
        config.workspace = args.workspace.expanduser().resolve()
    return config


def _auth_label(config: AppConfig) -> str:
    resolved = resolve_api_key(config_file_key=config.provider.api_key)
    if not resolved:
        return "not signed in"
    if resolved.kind == "byop":
        return f"pollen · {mask_key(resolved.key)}"
    if resolved.source == "env":
        return f"env · {mask_key(resolved.key)}"
    return f"key · {mask_key(resolved.key)}"


# ---------------------------------------------------------------------------
# Subcommands: login / logout / status
# ---------------------------------------------------------------------------

def cmd_login(console: Console) -> int:
    if not is_interactive():
        console.print("[red]login requires an interactive terminal.[/]")
        return 1
    try:
        perform_byop_login(save=True, console=console)
        return 0
    except Exception as exc:  # noqa: BLE001
        console.print(f"[bold red]Login failed:[/] {exc}")
        return 1


def cmd_logout(console: Console) -> int:
    perform_logout(console=console)
    return 0


def cmd_status(config: AppConfig, console: Console) -> int:
    from opencode_harness.logging_setup import log_path

    resolved = resolve_api_key(config_file_key=config.provider.api_key)
    console.print(f"[bold]OpenCodeHarness[/] v{__version__}")
    console.print(f"  endpoint:    {config.provider.base_url}")
    console.print(f"  model:       {config.provider.model}")
    console.print(f"  workspace:   {config.workspace}")
    console.print(f"  credentials: {credentials_path()}")
    console.print(f"  log file:    {log_path()}")
    if resolved:
        console.print(
            f"  api key:     {mask_key(resolved.key)}  "
            f"[dim]({resolved.source}/{resolved.kind})[/]"
        )
    else:
        console.print(f"  api key:     [yellow]not set[/]  → run [cyan]{_prog_name()} login[/]")
    return 0


def cmd_logs(console: Console, *, lines: int = 40) -> int:
    """Show log path + last N lines so you can confirm the agent is working."""
    from opencode_harness.logging_setup import DEFAULT_LOG_FILE, recent_activity

    path = DEFAULT_LOG_FILE
    console.print(f"[bold]Activity log[/]  {path}")
    if not path.exists():
        console.print("[dim]No log file yet — run the agent once to create it.[/]")
        console.print(f"[dim]Then: tail -f {path}[/]")
        return 0

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        tail = text.splitlines()[-lines:]
    except OSError as exc:
        console.print(f"[red]Cannot read log: {exc}[/]")
        return 1

    console.print(f"[dim]last {len(tail)} lines · live tail: tail -f {path}[/]\n")
    for line in tail:
        # Colorize levels lightly
        if " ERROR " in line or "│ ERROR" in line:
            console.print(f"[red]{line}[/]")
        elif " WARNING " in line or "│ WARN" in line:
            console.print(f"[yellow]{line}[/]")
        elif "tool start" in line or "shell exec" in line:
            console.print(f"[cyan]{line}[/]")
        elif "tool end" in line or "shell done" in line or "provider OK" in line:
            console.print(f"[green]{line}[/]")
        else:
            console.print(line)

    # Also show in-memory ring if this process had activity
    mem = recent_activity(5)
    if mem:
        console.print("\n[dim]in-memory (this process):[/]")
        for line in mem:
            console.print(f"  {line}")
    return 0


# ---------------------------------------------------------------------------
# Session wiring (shared by TUI + classic + one-shot)
# ---------------------------------------------------------------------------

def create_agent_loop(config: AppConfig, ui: TerminalUI, api_key: str) -> AgentLoop:
    client = OpenAICompatibleClient(config.provider, api_key=api_key)

    def confirm(command: str, reason: str) -> bool:
        return ui.confirm_destructive(command, reason)

    mode = getattr(config, "agent_mode", "build") or "build"
    registry = ToolRegistry(
        workspace=config.workspace,
        tool_config=config.tools,
        confirm_destructive=confirm,
        mode=mode if mode in ("build", "plan") else "build",  # type: ignore[arg-type]
    )

    def on_status(msg: str) -> None:
        ui.spinner_stop()
        ui.spinner_start(msg)

    def on_tool_start(tc, args) -> None:  # type: ignore[no-untyped-def]
        ui.spinner_stop()
        ui.tool_start(tc, args)
        ui.spinner_start(f"Running {tc.function.name}…")

    def on_tool_end(tc, result) -> None:  # type: ignore[no-untyped-def]
        ui.spinner_stop()
        ui.tool_end(tc, result)

    def on_assistant_text(text: str) -> None:
        ui.spinner_stop()
        ui.assistant_final(text)

    def on_stream_delta(chunk: str) -> None:
        ui.spinner_stop()
        ui.console.print(chunk, end="", highlight=False, soft_wrap=True)

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


def run_once(loop: AgentLoop, ui: TerminalUI, prompt: str) -> int:
    try:
        ui.spinner_start("Consulting model…")
        result = loop.run(prompt)
        ui.spinner_stop()
        return 2 if result.stopped_reason == "circuit_breaker" else 0
    except ProviderError as exc:
        ui.spinner_stop()
        ui.error(str(exc))
        return 1
    except KeyboardInterrupt:
        ui.spinner_stop()
        ui.warn("Interrupted.")
        return 130


def _handle_slash(line: str, loop: AgentLoop, ui: TerminalUI, config: AppConfig) -> bool:
    parts = line.strip().split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    if cmd in {"/exit", "/quit", "/q"}:
        ui.info("Goodbye.")
        raise SystemExit(0)
    if cmd == "/help":
        ui.console.print(
            """
[bold cyan]Slash commands[/]
  /help              Show this help
  /model [name]      Show or switch active model
  /models            List configured models
  /tools             List registered tools
  /reset             Clear conversation history
  /config            Show effective configuration
  /workspace [path]  Show or change workspace
  /exit              Quit
"""
        )
        return True
    if cmd == "/model":
        if not arg:
            ui.info(f"Active model: {config.provider.model}")
        else:
            loop.set_model(arg)
            ui.info(f"Switched model → {arg}")
        return True
    if cmd == "/models":
        for m in config.provider.models:
            mark = "→" if m == config.provider.model else " "
            ui.console.print(f"  {mark} {m}")
        return True
    if cmd == "/tools":
        for name in loop.registry.list_names():
            spec = loop.registry.get(name)
            desc = (spec.description[:80] + "…") if spec and len(spec.description) > 80 else (
                spec.description if spec else ""
            )
            ui.console.print(f"  [bold]{name}[/]  [dim]{desc}[/]")
        return True
    if cmd == "/reset":
        loop.reset()
        ui.info("Conversation history cleared.")
        return True
    if cmd == "/config":
        ui.console.print(
            f"  base_url:   {config.provider.base_url}\n"
            f"  model:      {config.provider.model}\n"
            f"  workspace:  {config.workspace}\n"
            f"  bash_timeout: {config.tools.bash_timeout}s\n"
            f"  max_tool_rounds: {config.tools.max_tool_rounds}\n"
            f"  api_key:    {_auth_label(config)}"
        )
        return True
    if cmd == "/workspace":
        if not arg:
            ui.info(f"Workspace: {config.workspace}")
        else:
            new_ws = Path(arg).expanduser().resolve()
            if not new_ws.is_dir():
                ui.error(f"Not a directory: {new_ws}")
            else:
                config.workspace = new_ws
                loop.registry.workspace = new_ws
                loop.reset()
                ui.info(f"Workspace → {new_ws} (history reset)")
        return True

    ui.warn(f"Unknown command: {cmd}  (try /help)")
    return True


def classic_repl(loop: AgentLoop, ui: TerminalUI, config: AppConfig) -> int:
    history_path = DEFAULT_CONFIG_DIR / "history"
    DEFAULT_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    session: PromptSession[str] = PromptSession(
        history=FileHistory(str(history_path)),
        style=PROMPT_STYLE,
        enable_history_search=True,
    )
    ui.banner(
        model=config.provider.model,
        base_url=config.provider.base_url,
        workspace=str(config.workspace),
    )
    ui.info(f"Auth: {_auth_label(config)}")

    while True:
        try:
            line = session.prompt([("class:prompt", "you › ")])
        except KeyboardInterrupt:
            ui.console.print()
            continue
        except EOFError:
            ui.console.print()
            ui.info("Goodbye.")
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
        run_once(loop, ui, line)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    console = Console()

    if args.init:
        path = ensure_default_config()
        console.print(f"Wrote default config → {path}")
        return 0

    # Ensure config dir / starter file exists
    if not DEFAULT_CONFIG_PATH.exists() and not (DEFAULT_CONFIG_DIR / "config.json").exists():
        ensure_default_config()

    # ---- logging (always on — file at INFO, console if -v) ------------
    from opencode_harness.logging_setup import get_logger, setup_logging

    level = "DEBUG" if args.verbose else ("WARNING" if args.quiet else "INFO")
    # One-shot / verbose: also print logger lines to stderr
    tokens_preview = list(args.command_or_prompt or [])
    is_sub = bool(tokens_preview and tokens_preview[0] in {"login", "logout", "status", "logs"})
    mirror_console = bool(args.verbose or (tokens_preview and not is_sub))
    log_file = setup_logging(
        level=level,
        log_file=args.log_file,
        console=mirror_console and not args.quiet,
        quiet=args.quiet,
    )
    log = get_logger("cli")
    log.debug("cli start argv=%s", argv or sys.argv[1:])

    config = _apply_overrides(load_config(args.config), args)
    tokens = list(args.command_or_prompt or [])

    # ---- subcommands -------------------------------------------------
    if tokens and tokens[0] in {"login", "logout", "status", "logs"}:
        sub = tokens[0]
        if sub == "login":
            return cmd_login(console)
        if sub == "logout":
            return cmd_logout(console)
        if sub == "logs":
            return cmd_logs(console)
        return cmd_status(config, console)

    # ---- resolve API key (BYOP first-run if missing) ------------------
    try:
        api_key = require_api_key(
            config_file_key=config.provider.api_key,
            console=console,
        )
    except Exception as exc:  # noqa: BLE001
        console.print(f"[bold red]{exc}[/]")
        return 1

    # ---- one-shot goal -----------------------------------------------
    if tokens:
        goal = " ".join(tokens)
        log.info("one-shot mode  goal=%r  log_file=%s", goal[:80], log_file)
        ui = TerminalUI(
            syntax_theme=config.ui.syntax_theme,
            show_tool_args=config.ui.show_tool_args,
        )
        ui.info(f"Logging → {log_file}")
        loop = create_agent_loop(config, ui, api_key)
        try:
            ui.banner(
                model=config.provider.model,
                base_url=config.provider.base_url,
                workspace=str(config.workspace),
            )
            return run_once(loop, ui, goal)
        finally:
            loop.client.close()

    # ---- interactive -------------------------------------------------
    # Optional experimental full-screen mode
    if args.tui and is_interactive():
        try:
            from opencode_harness.ui.tui import run_tui
        except ImportError as exc:
            console.print(
                f"[yellow]Full-screen TUI unavailable ({exc}). "
                "Using scrollback session. Install textual: pip install textual[/]"
            )
        else:
            log.info("launching full-screen TUI  log_file=%s", log_file)
            return run_tui(
                config,
                api_key=api_key,
                auth_label=_auth_label(config),
            )

    # Default: Claude / OpenCode-style scrollback + fluid ASCII art
    from opencode_harness.ui.session import run_session

    log.info("launching scrollback session  log_file=%s", log_file)
    return run_session(
        config,
        api_key=api_key,
        auth_label=_auth_label(config),
    )


if __name__ == "__main__":
    sys.exit(main())
