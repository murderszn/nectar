"""Unit tests for destructive-command detection."""

from opencode_harness.tools.safety import is_destructive


def test_rm_rf_blocked():
    ok, reason = is_destructive("rm -rf /tmp/foo")
    assert ok is True
    assert reason


def test_chmod_blocked():
    ok, _ = is_destructive("chmod 777 /etc/passwd")
    assert ok is True


def test_safe_command():
    ok, reason = is_destructive("ls -la src/")
    assert ok is False
    assert reason == ""


def test_git_status_safe():
    ok, _ = is_destructive("git status")
    assert ok is False


def test_git_reset_hard_blocked():
    ok, _ = is_destructive("git reset --hard HEAD")
    assert ok is True


def test_extra_pattern():
    ok, reason = is_destructive("deploy --prod", extra_patterns=[r"--prod"])
    assert ok is True
    assert "custom" in reason
