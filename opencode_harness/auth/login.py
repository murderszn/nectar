"""
Interactive login UX — mirrors `sprout login` / first-run Pollen prompt.
"""

from __future__ import annotations

import getpass
import sys
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from opencode_harness.auth.byop import (
    ByopLoginResult,
    resolve_byop_client_id,
    run_byop_login,
)
from opencode_harness.auth.store import (
    clear_stored_key,
    credentials_path,
    mask_key,
    resolve_api_key,
    save_api_key,
)


def is_interactive() -> bool:
    return bool(sys.stdin.isatty() and sys.stdout.isatty())


def perform_byop_login(*, save: bool = True, console: Optional[Console] = None) -> str:
    """
    Run the full BYOP device flow and optionally persist the sk_ token.

    Prints the same style of UX as Sprout:
      • show user code + verify URL
      • open browser
      • poll with live elapsed timer
      • save masked key path on success
    """
    console = console or Console()
    client_id = resolve_byop_client_id()
    if not client_id:
        raise RuntimeError(
            "BYOP is not configured — set POLLINATIONS_BYOP_KEY or ship a publishable pk_ App Key."
        )

    console.print()
    console.print(Panel(
        Text.from_markup(
            "[bold]Sign in with Pollen[/]\n"
            "OpenCodeHarness will use [cyan]your[/] Pollinations balance for inference —\n"
            "nothing is charged to the app author."
        ),
        border_style="cyan",
        title="🌸 Pollen · BYOP",
        title_align="left",
    ))

    def on_device_code(user_code: str, verify_url: str, opened: bool) -> None:
        console.print()
        console.print(f"  [bold]Enter this code[/] at [cyan underline]{verify_url}[/]")
        console.print(f"  [bold yellow]{user_code}[/]\n")
        if opened:
            console.print("  [dim]Opened your browser — approve access, then come back here.[/]\n")
        else:
            console.print("  [dim]Could not open a browser automatically — visit the URL above.[/]\n")

    def on_waiting(elapsed_ms: int) -> None:
        secs = round(elapsed_ms / 1000)
        console.print(f"  [dim]waiting for approval… {secs}s[/]", end="\r")

    def on_authorized(user) -> None:  # type: ignore[no-untyped-def]
        console.print()
        if user and user.preferred_username:
            console.print(f"  [green]✓ authorized as {user.preferred_username}[/]")
        else:
            console.print("  [green]✓ authorized[/]")

    result: ByopLoginResult = run_byop_login(
        client_id,
        on_device_code=on_device_code,
        on_waiting=on_waiting,
        on_authorized=on_authorized,
    )

    if save:
        username = result.user.preferred_username if result.user else None
        path = save_api_key(result.access_token, kind="byop", username=username)
        console.print(
            f"\n[green]Saved[/] (masked: [bold]{mask_key(result.access_token)}[/]) "
            f"to [dim]{path}[/]"
        )

    return result.access_token


def prompt_manual_key(*, save: bool = True, console: Optional[Console] = None) -> str:
    """Paste an existing sk_ key (fallback when user declines BYOP)."""
    console = console or Console()
    console.print(
        "\nPaste an existing [cyan]sk_…[/] key "
        f"(or run [bold]honey login[/] for Pollen BYOP).\n"
    )
    try:
        key = getpass.getpass("API key: ").strip()
    except (EOFError, KeyboardInterrupt) as exc:
        raise RuntimeError("Login cancelled.") from exc
    if not key:
        raise RuntimeError("Empty API key.")

    if save:
        path = save_api_key(key, kind="manual")
        console.print(f"[green]Saved[/] (masked: [bold]{mask_key(key)}[/]) to [dim]{path}[/]")
    return key


def require_api_key(
    *,
    config_file_key: str = "",
    console: Optional[Console] = None,
    force_login: bool = False,
) -> str:
    """
    First-run key flow (Sprout-parity):

      env / credentials / config → return
      else interactive:
        ask BYOP? → device flow
        else → paste sk_
    """
    console = console or Console()
    if not force_login:
        resolved = resolve_api_key(config_file_key=config_file_key)
        if resolved:
            return resolved.key

    if not is_interactive():
        raise RuntimeError(
            "No API key found. Set POLLINATIONS_API_KEY, run "
            "`honey login` in a TTY, or add provider.api_key to config."
        )

    client_id = resolve_byop_client_id()
    if client_id:
        console.print()
        try:
            answer = console.input(
                "[bold]Sign in with Pollen[/] at enter.pollinations.ai? "
                "(uses your balance — recommended) [Y/n] "
            ).strip().lower()
        except (EOFError, KeyboardInterrupt) as exc:
            raise RuntimeError("Login cancelled.") from exc

        if answer in {"", "y", "yes"}:
            return perform_byop_login(save=True, console=console)

    return prompt_manual_key(save=True, console=console)


def perform_logout(*, console: Optional[Console] = None) -> None:
    console = console or Console()
    if clear_stored_key():
        console.print(f"[green]Cleared stored key[/] from [dim]{credentials_path()}[/]")
    else:
        console.print("[dim]No stored credentials to clear.[/]")
        console.print(
            "If you use an env var (POLLINATIONS_API_KEY), unset it in your shell."
        )
