"""
Destructive-command detection for the bash tool.

Patterns are intentionally conservative: false positives are preferred
over silently allowing `rm -rf /` style accidents. Matched commands still
run if the human confirms with Y at the terminal.
"""

from __future__ import annotations

import re
from typing import Iterable, Optional


# Compiled once at import for speed
_DEFAULT_PATTERNS: list[re.Pattern[str]] = [
    # Recursive / force remove
    re.compile(r"\brm\s+(-[a-zA-Z]*[rR][a-zA-Z]*f|[a-zA-Z]*f[a-zA-Z]*[rR]|-[rR]\s+-[fF]|-[fF]\s+-[rR])\b"),
    re.compile(r"\brm\s+-[^\s]*r[^\s]*\b"),
    re.compile(r"\brm\s+--recursive\b"),
    # Wipe / format style
    re.compile(r"\bmkfs(\.\w+)?\b"),
    re.compile(r"\bdd\s+if=", re.I),
    re.compile(r">\s*/dev/sd"),
    # Permission escalation & chmod of sensitive trees
    re.compile(r"\bchmod\b"),
    re.compile(r"\bchown\b"),
    re.compile(r"\bchgrp\b"),
    # System mutation
    re.compile(r"\bsudo\b"),
    re.compile(r"\bdoas\b"),
    re.compile(r"\bshutdown\b"),
    re.compile(r"\breboot\b"),
    re.compile(r"\bhalt\b"),
    re.compile(r"\bpoweroff\b"),
    re.compile(r"\binit\s+[06]\b"),
    # Package / system delete
    re.compile(r"\bapt(-get)?\s+remove\b"),
    re.compile(r"\bapt(-get)?\s+purge\b"),
    re.compile(r"\byum\s+remove\b"),
    re.compile(r"\bdnf\s+remove\b"),
    re.compile(r"\bbrew\s+uninstall\b"),
    re.compile(r"\bpip(3)?\s+uninstall\b"),
    # Git destructive
    re.compile(r"\bgit\s+push\s+.*--force\b"),
    re.compile(r"\bgit\s+push\s+.*-f\b"),
    re.compile(r"\bgit\s+reset\s+--hard\b"),
    re.compile(r"\bgit\s+clean\s+.*-[a-zA-Z]*f"),
    # Disk / partition
    re.compile(r"\bdiskutil\s+(erase|partition|unmount)\b", re.I),
    re.compile(r"\bparted\b"),
    re.compile(r"\bfdisk\b"),
    # Redirect wipe of important paths
    re.compile(r">\s*/etc/"),
    re.compile(r"\bmv\s+.+\s+/dev/null\b"),
    # Fork bombs / resource bombs
    re.compile(r":\(\)\s*\{\s*:\|:\s*&\s*\}\s*;\s*:"),
    re.compile(r"\bkill\s+-9\s+-1\b"),
    re.compile(r"\bkillall\b"),
    # Write outside via shred / unlink bulk
    re.compile(r"\bshred\b"),
    re.compile(r"\bunlink\b"),
    re.compile(r"\brmdir\b"),
    # macOS SIP / launchctl teardown
    re.compile(r"\blaunchctl\s+(bootout|unload)\b"),
]


def is_destructive(command: str, extra_patterns: Optional[Iterable[str]] = None) -> tuple[bool, str]:
    """
    Return (True, reason) if the command looks destructive.

    `reason` is a short human-readable explanation for the confirmation UI.
    """
    cmd = command.strip()
    if not cmd:
        return False, ""

    for pattern in _DEFAULT_PATTERNS:
        if pattern.search(cmd):
            return True, f"matched safety pattern: /{pattern.pattern}/"

    if extra_patterns:
        for raw in extra_patterns:
            try:
                if re.search(raw, cmd, flags=re.I):
                    return True, f"matched custom pattern: /{raw}/"
            except re.error:
                # Bad user regex — skip rather than crash the agent loop
                continue

    return False, ""
