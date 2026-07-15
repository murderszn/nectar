"""
Configuration loading and validation for OpenCodeHarness.

Supports YAML or JSON at ~/.opencode_harness/config.yaml (default).
Environment variables always take precedence over file values for secrets.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

# Optional YAML support — JSON works without PyYAML
try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]


DEFAULT_CONFIG_DIR = Path.home() / ".opencode_harness"
DEFAULT_CONFIG_PATH = DEFAULT_CONFIG_DIR / "config.yaml"
DEFAULT_BASE_URL = "https://gen.pollinations.ai/v1"
DEFAULT_MODEL = "kimi"
DEFAULT_TIMEOUT = 120.0
DEFAULT_BASH_TIMEOUT = 45
DEFAULT_MAX_TOOL_ROUNDS = 12
DEFAULT_WORKSPACE = Path.cwd()


@dataclass
class ProviderConfig:
    """OpenAI-compatible chat-completions provider settings."""

    base_url: str = DEFAULT_BASE_URL
    api_key: str = ""
    model: str = DEFAULT_MODEL
    # Extra models the user can /switch to without editing config
    models: list[str] = field(default_factory=lambda: ["kimi", "deepseek", "hermes", "openai"])
    timeout: float = DEFAULT_TIMEOUT
    temperature: float = 0.2
    max_tokens: Optional[int] = None
    # stream=False for tool turns; final text may still be streamed
    stream_final: bool = True


@dataclass
class ToolConfig:
    """Local tool execution constraints."""

    bash_timeout: int = DEFAULT_BASH_TIMEOUT
    max_tool_rounds: int = DEFAULT_MAX_TOOL_ROUNDS
    # Paths outside workspace are blocked for write (read is allowed with warn)
    enforce_workspace_boundary: bool = True
    # Extra command patterns treated as destructive (regex strings)
    extra_destructive_patterns: list[str] = field(default_factory=list)


@dataclass
class UIConfig:
    """Terminal presentation preferences."""

    show_tool_args: bool = True
    syntax_theme: str = "monokai"
    spinner_style: str = "dots"
    # Design theme: rainbow (default) | prism | pulse | honey | quiet
    theme: str = "rainbow"


@dataclass
class AppConfig:
    """Root application configuration."""

    provider: ProviderConfig = field(default_factory=ProviderConfig)
    tools: ToolConfig = field(default_factory=ToolConfig)
    ui: UIConfig = field(default_factory=UIConfig)
    workspace: Path = field(default_factory=lambda: DEFAULT_WORKSPACE)
    system_prompt_extra: str = ""
    # OpenCode-style agent modes: build = full tools; plan = read-only explore
    agent_mode: str = "build"

    def resolve_api_key(self) -> str:
        """
        Prefer env → ~/.opencode_harness/credentials.json → config provider.api_key.

        Thin wrapper over auth.store for callers that only need the raw string.
        """
        # Local import avoids a circular dependency at module load time.
        from opencode_harness.auth.store import resolve_api_key as _resolve

        found = _resolve(config_file_key=self.provider.api_key)
        return found.key if found else ""


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge override into base (mutates base, returns it)."""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def _load_raw(path: Path) -> dict[str, Any]:
    """Load YAML or JSON config file into a plain dict."""
    if not path.exists():
        return {}

    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()

    if suffix in {".yaml", ".yml"}:
        if yaml is None:
            raise RuntimeError(
                "PyYAML is required for .yaml configs. "
                "Install with: pip install pyyaml  — or use config.json instead."
            )
        data = yaml.safe_load(text) or {}
    elif suffix == ".json":
        data = json.loads(text) if text.strip() else {}
    else:
        # Try YAML first, then JSON
        if yaml is not None:
            try:
                data = yaml.safe_load(text) or {}
            except Exception:
                data = json.loads(text) if text.strip() else {}
        else:
            data = json.loads(text) if text.strip() else {}

    if not isinstance(data, dict):
        raise ValueError(f"Config root must be a mapping, got {type(data).__name__}")
    return data


def _from_dict(data: dict[str, Any]) -> AppConfig:
    """Build AppConfig from a nested dict (file + env overlays)."""
    prov = data.get("provider") or {}
    tools = data.get("tools") or {}
    ui = data.get("ui") or {}

    provider = ProviderConfig(
        base_url=str(prov.get("base_url", DEFAULT_BASE_URL)).rstrip("/"),
        api_key=str(prov.get("api_key", "") or ""),
        model=str(prov.get("model", DEFAULT_MODEL)),
        models=list(prov.get("models") or ["kimi", "deepseek", "hermes", "openai"]),
        timeout=float(prov.get("timeout", DEFAULT_TIMEOUT)),
        temperature=float(prov.get("temperature", 0.2)),
        max_tokens=prov.get("max_tokens"),
        stream_final=bool(prov.get("stream_final", True)),
    )

    tool_cfg = ToolConfig(
        bash_timeout=int(tools.get("bash_timeout", DEFAULT_BASH_TIMEOUT)),
        max_tool_rounds=int(tools.get("max_tool_rounds", DEFAULT_MAX_TOOL_ROUNDS)),
        enforce_workspace_boundary=bool(tools.get("enforce_workspace_boundary", True)),
        extra_destructive_patterns=list(tools.get("extra_destructive_patterns") or []),
    )

    ui_cfg = UIConfig(
        show_tool_args=bool(ui.get("show_tool_args", True)),
        syntax_theme=str(ui.get("syntax_theme", "monokai")),
        spinner_style=str(ui.get("spinner_style", "dots")),
        theme=str(ui.get("theme", "rainbow")),
    )

    workspace_raw = data.get("workspace") or str(DEFAULT_WORKSPACE)
    workspace = Path(workspace_raw).expanduser().resolve()

    mode = str(data.get("agent_mode") or "build").strip().lower()
    if mode not in {"build", "plan"}:
        mode = "build"

    return AppConfig(
        provider=provider,
        tools=tool_cfg,
        ui=ui_cfg,
        workspace=workspace,
        system_prompt_extra=str(data.get("system_prompt_extra") or ""),
        agent_mode=mode,
    )


def load_config(path: Optional[Path | str] = None) -> AppConfig:
    """
    Load application config from disk, applying env overrides.

    Lookup order:
      1. Explicit --config path
      2. OPENCODE_HARNESS_CONFIG env
      3. ~/.opencode_harness/config.yaml
      4. ~/.opencode_harness/config.json
      5. Built-in defaults
    """
    candidates: list[Path] = []
    if path:
        candidates.append(Path(path).expanduser())
    env_path = os.environ.get("OPENCODE_HARNESS_CONFIG")
    if env_path:
        candidates.append(Path(env_path).expanduser())
    candidates.extend(
        [
            DEFAULT_CONFIG_PATH,
            DEFAULT_CONFIG_DIR / "config.json",
        ]
    )

    raw: dict[str, Any] = {}
    for candidate in candidates:
        if candidate.exists():
            raw = _load_raw(candidate)
            break

    # Env overlays for non-secret provider settings
    env_overlay: dict[str, Any] = {"provider": {}}
    if os.environ.get("OPENCODE_HARNESS_BASE_URL"):
        env_overlay["provider"]["base_url"] = os.environ["OPENCODE_HARNESS_BASE_URL"]
    if os.environ.get("OPENCODE_HARNESS_MODEL"):
        env_overlay["provider"]["model"] = os.environ["OPENCODE_HARNESS_MODEL"]
    if os.environ.get("OPENCODE_HARNESS_WORKSPACE"):
        env_overlay["workspace"] = os.environ["OPENCODE_HARNESS_WORKSPACE"]

    if env_overlay["provider"] or "workspace" in env_overlay:
        raw = _deep_merge(dict(raw), env_overlay)

    return _from_dict(raw)


def ensure_default_config(path: Path = DEFAULT_CONFIG_PATH) -> Path:
    """
    Write a starter config if none exists. Returns the path used.
    """
    if path.exists():
        return path

    path.parent.mkdir(parents=True, exist_ok=True)
    example = """\
# OpenCodeHarness configuration
# Docs: https://github.com/example/opencode-harness (local package)

provider:
  # OpenAI-compatible base URL (no trailing slash required)
  base_url: "https://gen.pollinations.ai/v1"
  # Prefer: `honey login` (BYOP) or POLLINATIONS_API_KEY
  # Do not put sk_ secrets here — they live in credentials.json
  api_key: ""
  # Strong tool-calling defaults; swap to "hermes" for local Ollama
  model: "kimi"
  models:
    - kimi
    - deepseek
    - hermes
    - openai
  timeout: 120
  temperature: 0.2
  stream_final: true

tools:
  bash_timeout: 45
  max_tool_rounds: 12
  enforce_workspace_boundary: true
  extra_destructive_patterns: []

ui:
  show_tool_args: true
  syntax_theme: monokai
  spinner_style: dots
  # rainbow | prism | pulse | honey | quiet
  theme: rainbow

# Absolute path or leave unset to use the process CWD
# workspace: "/path/to/project"

system_prompt_extra: ""
"""
    path.write_text(example, encoding="utf-8")
    return path
