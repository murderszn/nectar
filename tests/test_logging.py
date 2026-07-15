"""Logging setup and activity ring tests."""

from pathlib import Path

from opencode_harness.logging_setup import (
    get_logger,
    recent_activity,
    setup_logging,
)


def test_setup_writes_file(tmp_path: Path):
    path = tmp_path / "test.log"
    setup_logging(level="INFO", log_file=path, console=False)
    log = get_logger("test")
    log.info("tool is working")
    log.warning("heads up")

    # Handlers flush on emit for Stream/File; force close via reconfigure
    setup_logging(level="INFO", log_file=path, console=False)

    text = path.read_text(encoding="utf-8")
    assert "tool is working" in text
    assert "heads up" in text


def test_activity_ring():
    path = Path("/tmp/och-test-activity.log")  # noqa: S108 — test only
    setup_logging(level="INFO", log_file=path, console=False)
    log = get_logger("ring")
    log.info("alpha event")
    log.info("beta event")
    recent = recent_activity(10)
    assert any("alpha event" in line for line in recent)
    assert any("beta event" in line for line in recent)
