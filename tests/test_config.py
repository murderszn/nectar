"""Config loading tests."""

from pathlib import Path

from opencode_harness.config import load_config


def test_defaults():
    cfg = load_config(Path("/nonexistent/config.yaml"))
    assert cfg.provider.base_url == "https://gen.pollinations.ai/v1"
    assert cfg.provider.model == "kimi"
    assert cfg.tools.max_tool_rounds == 12
    assert cfg.tools.bash_timeout == 45


def test_yaml_load(tmp_path: Path, monkeypatch):
    # Isolate from real user config
    monkeypatch.delenv("OPENCODE_HARNESS_CONFIG", raising=False)
    monkeypatch.delenv("OPENCODE_HARNESS_MODEL", raising=False)
    p = tmp_path / "c.yaml"
    p.write_text(
        """
provider:
  base_url: "http://localhost:11434/v1"
  model: "hermes"
tools:
  max_tool_rounds: 5
""",
        encoding="utf-8",
    )
    cfg = load_config(p)
    assert cfg.provider.model == "hermes"
    assert cfg.provider.base_url == "http://localhost:11434/v1"
    assert cfg.tools.max_tool_rounds == 5
