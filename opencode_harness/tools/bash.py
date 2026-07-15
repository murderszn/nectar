"""
execute_bash_command — local subprocess tool with timeout + safety gates.
"""

from __future__ import annotations

import subprocess
import time
from typing import Callable, Optional

from opencode_harness.logging_setup import get_logger
from opencode_harness.tools.safety import is_destructive

log = get_logger("tools.bash")

ConfirmCallback = Callable[[str, str], bool]
"""(command, reason) -> True if user allows execution."""


def run_bash(
    command: str,
    *,
    timeout: int = 45,
    cwd: Optional[str] = None,
    confirm: Optional[ConfirmCallback] = None,
    extra_destructive_patterns: Optional[list[str]] = None,
) -> str:
    """
    Execute a shell command via subprocess.Popen.

    Returns a structured multi-line string (exit code, stdout, stderr)
    so the model always gets parseable feedback — including timeouts
    and denied destructive commands.
    """
    if not command or not command.strip():
        return "ERROR: empty command"

    destructive, reason = is_destructive(command, extra_destructive_patterns)
    if destructive:
        log.warning("destructive command gated: %s (%s)", command[:120], reason)
        allowed = False
        if confirm is not None:
            allowed = confirm(command, reason)
        if not allowed:
            log.warning("destructive command BLOCKED by user")
            return (
                "BLOCKED: command flagged as potentially destructive.\n"
                f"Reason: {reason}\n"
                f"Command: {command}\n"
                "User denied execution (or no confirmation callback was available)."
            )
        log.info("destructive command APPROVED by user")

    log.info("shell exec  timeout=%ss  cwd=%s  cmd=%r", timeout, cwd, command[:200])
    t0 = time.monotonic()
    try:
        proc = subprocess.Popen(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
            text=True,
            # Avoid leaking the parent agent env wholesale if desired later;
            # for a local developer agent we inherit env (PATH, venv, etc.).
        )
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            # Drain remaining pipes after kill
            stdout, stderr = proc.communicate()
            log.error("shell TIMEOUT after %ss  cmd=%r", timeout, command[:120])
            return (
                f"TIMEOUT: command exceeded {timeout}s and was killed.\n"
                f"--- stdout ---\n{(stdout or '').strip()}\n"
                f"--- stderr ---\n{(stderr or '').strip()}"
            )
    except OSError as exc:
        log.error("shell spawn failed: %s", exc)
        return f"ERROR: failed to spawn process: {exc}"

    exit_code = proc.returncode if proc.returncode is not None else -1
    out = (stdout or "").rstrip()
    err = (stderr or "").rstrip()
    elapsed = time.monotonic() - t0
    log.info(
        "shell done  exit=%s  %.2fs  stdout_chars=%d  stderr_chars=%d",
        exit_code,
        elapsed,
        len(out),
        len(err),
    )

    # Cap extremely large outputs so we don't blow the context window
    max_chars = 40_000
    if len(out) > max_chars:
        out = out[:max_chars] + f"\n... [stdout truncated at {max_chars} chars]"
    if len(err) > max_chars:
        err = err[:max_chars] + f"\n... [stderr truncated at {max_chars} chars]"

    parts = [f"exit_code: {exit_code}"]
    parts.append("--- stdout ---")
    parts.append(out if out else "(empty)")
    parts.append("--- stderr ---")
    parts.append(err if err else "(empty)")
    return "\n".join(parts)
