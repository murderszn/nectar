"""
Activity logging for OpenCodeHarness.

Goals:
  1. Always write a rotating file log so you can `tail -f` while the TUI runs.
  2. Keep an in-memory activity ring for the full-screen status feed.
  3. Optionally mirror INFO+ to stderr (--verbose / classic mode).

Default log path: ~/.opencode_harness/logs/harness.log
"""

from __future__ import annotations

import logging
import sys
import threading
from collections import deque
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Callable, Deque, Optional

from opencode_harness.config import DEFAULT_CONFIG_DIR

LOG_DIR = DEFAULT_CONFIG_DIR / "logs"
DEFAULT_LOG_FILE = LOG_DIR / "harness.log"
LOGGER_NAME = "opencode_harness"

# Subscribers notified on every activity line (TUI feed, etc.)
_listeners: list[Callable[[str, str], None]] = []
_listener_lock = threading.Lock()

# Ring buffer of recent human-readable activity lines
_activity: Deque[str] = deque(maxlen=200)
_activity_lock = threading.Lock()

_configured = False


class _ActivityHandler(logging.Handler):
    """Push formatted records into the ring buffer + optional listeners."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            with _activity_lock:
                _activity.append(msg)
            with _listener_lock:
                listeners = list(_listeners)
            for cb in listeners:
                try:
                    cb(record.levelname, record.getMessage())
                except Exception:  # noqa: BLE001 — never break logging
                    pass
        except Exception:  # noqa: BLE001
            self.handleError(record)


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """Return a child logger under opencode_harness.*"""
    if name and not name.startswith(LOGGER_NAME):
        return logging.getLogger(f"{LOGGER_NAME}.{name}")
    return logging.getLogger(name or LOGGER_NAME)


def setup_logging(
    *,
    level: str = "INFO",
    log_file: Optional[Path] = None,
    console: bool = False,
    quiet: bool = False,
) -> Path:
    """
    Configure package logging. Safe to call multiple times (idempotent reset).

    Returns the path of the active log file.
    """
    global _configured

    path = Path(log_file) if log_file else DEFAULT_LOG_FILE
    path.parent.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger(LOGGER_NAME)
    root.handlers.clear()
    root.setLevel(logging.DEBUG)  # handlers filter; keep logger open
    root.propagate = False

    numeric = getattr(logging, level.upper(), logging.INFO)
    if quiet:
        numeric = logging.WARNING

    fmt = logging.Formatter(
        fmt="%(asctime)s │ %(levelname)-5s │ %(name)s │ %(message)s",
        datefmt="%H:%M:%S",
    )
    # File gets full timestamps for post-mortems
    file_fmt = logging.Formatter(
        fmt="%(asctime)s │ %(levelname)-5s │ %(name)s │ %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    fh = RotatingFileHandler(
        path,
        maxBytes=2_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(file_fmt)
    root.addHandler(fh)

    ah = _ActivityHandler()
    ah.setLevel(numeric)
    ah.setFormatter(fmt)
    root.addHandler(ah)

    if console:
        sh = logging.StreamHandler(sys.stderr)
        sh.setLevel(numeric)
        sh.setFormatter(fmt)
        root.addHandler(sh)

    _configured = True
    root.info(
        "logging started  level=%s  file=%s  console=%s",
        level.upper(),
        path,
        console,
    )
    return path


def ensure_logging(**kwargs) -> Path:  # type: ignore[no-untyped-def]
    """Configure once with defaults if nothing has been set up yet."""
    if not _configured:
        return setup_logging(**kwargs)
    return Path(kwargs.get("log_file") or DEFAULT_LOG_FILE)


def add_activity_listener(cb: Callable[[str, str], None]) -> None:
    """Subscribe to (level, message) for live UI feeds."""
    with _listener_lock:
        if cb not in _listeners:
            _listeners.append(cb)


def remove_activity_listener(cb: Callable[[str, str], None]) -> None:
    with _listener_lock:
        try:
            _listeners.remove(cb)
        except ValueError:
            pass


def recent_activity(n: int = 30) -> list[str]:
    with _activity_lock:
        return list(_activity)[-n:]


def log_path() -> Path:
    return DEFAULT_LOG_FILE


def heartbeat(label: str) -> str:
    """Short timestamped status string for the TUI status bar."""
    ts = datetime.now(timezone.utc).astimezone().strftime("%H:%M:%S")
    return f"{ts}  {label}"
