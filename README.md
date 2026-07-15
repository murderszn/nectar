# Nectar · honey

**Open coding agent for the terminal** — Claude/OpenCode-style session UX, full local toolbelt, and **Pollinations Pollen (BYOP)** as login/payment.

Package name: `opencode-harness` · primary command: **`honey`**

Designed for **OpenAI-compatible** endpoints out of the box:

| Provider | Base URL | Notes |
|----------|----------|--------|
| **Pollinations** (default) | `https://gen.pollinations.ai/v1` | Set `POLLINATIONS_API_KEY` |
| **Ollama** | `http://localhost:11434/v1` | e.g. model `hermes`, `llama3.1` |
| LM Studio / vLLM / LiteLLM | their `/v1` URL | Same wire protocol |

Default routing model: **`kimi`** (or switch to **`deepseek`** / local **`hermes`**) for strong tool-calling behavior.

---

## Quick start

```bash
# 1. Clone / enter this directory
cd /path/to/nectar

# 2. Create a virtualenv (recommended)
python3 -m venv .venv
source .venv/bin/activate

# 3. Install
pip install -e .

# 4. Config + Pollen login (same BYOP flow as Sprout)
honey --init
honey login                      # browser device code → enter.pollinations.ai

# 5. Interactive session (Claude / OpenCode-style scrollback + ASCII art)
honey

# Or one-shot:
honey "List Python files in the workspace and summarize the project"
```

**Primary command:** `honey`  
**Aliases:** `opencode-harness`, `och`, `python -m opencode_harness`

### Auth (Pollinations BYOP)

Matches [Sprout](https://github.com/murderszn/sprout) / [Bring Your Own Pollen](https://github.com/pollinations/pollinations/blob/main/BRING_YOUR_OWN_POLLEN.md):

| Command | Action |
|---------|--------|
| `honey login` | Device flow → browser → save `sk_` to `~/.opencode_harness/credentials.json` (mode 600) |
| `honey logout` | Clear stored credentials |
| `honey status` | Show endpoint, model, masked key source |

**Resolution order:** env (`POLLINATIONS_API_KEY` …) → `credentials.json` → `provider.api_key` in config → interactive first-run prompt (BYOP recommended).

First launch without a key asks:

> Sign in with Pollen at enter.pollinations.ai? (uses your balance — recommended)

### Interactive session (default)

Running `honey` opens a **scrollback chat** like Claude Code / OpenCode — type a goal, watch tools run inline, read the answer. No alt-screen takeover; terminal history stays usable.

Visual identity is custom **fluid ASCII art** (gradient NECTAR wordmark, nectar drop mark, wave separators).

```
  ❯ your goal here
  ⚙ execute_bash_command
  ╰─ ls -la
  ◌ running …
  ◈ harness
  … markdown answer …
```

| Input | Action |
|-------|--------|
| goal text | Run the agent loop |
| `/help` `/model` `/logs` `/reset` `/exit` | Session commands |
| `Ctrl+C` | Clear the current line |
| `Ctrl+D` or `/exit` | Quit |

Optional full-screen mode: `honey --tui`

### Activity logging (know when tools are working)

Every run writes a rotating log so you can see model calls, tool starts/ends, shell exit codes, and timings:

```bash
# Path (shown on splash + `status`)
~/.opencode_harness/logs/harness.log

# Live tail in another terminal while the session runs
tail -f ~/.opencode_harness/logs/harness.log

# Dump recent lines
honey logs

# Mirror logs to stderr
honey -v
```

**What gets logged**

| Event | Example |
|-------|---------|
| User goal | `▶ user goal: …` |
| Model request/response | `⟳ model request` / `✓ model response … 1.2s` |
| Provider HTTP | `POST …/chat/completions` / `provider OK` |
| Tool start/end | `⚙ tool start execute_bash_command` / `↳ tool end … outcome=ok` |
| Shell | `shell exec` / `shell done exit=0 0.05s` |
| Safety gate | `destructive command BLOCKED/APPROVED` |

In session, tools print inline with spinners; `/logs` shows recent file log lines.

### Local Ollama example

```yaml
# ~/.opencode_harness/config.yaml
provider:
  base_url: "http://localhost:11434/v1"
  api_key: "ollama"   # often ignored; any non-empty string is fine
  model: "hermes"
```

```bash
honey --base-url http://localhost:11434/v1 --model hermes
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  CLI (prompt_toolkit history + Rich panels/spinners)        │
└───────────────────────────┬─────────────────────────────────┘
                            │ user goal
┌───────────────────────────▼─────────────────────────────────┐
│  AgentLoop                                                  │
│   • system prompt + tool JSON schemas                       │
│   • circuit breaker (max 12 tool rounds / prompt)           │
│   • append role=tool messages → re-query model              │
└───────────────┬─────────────────────────┬───────────────────┘
                │ OpenAI chat.completions │ dispatch()
┌───────────────▼───────────┐   ┌─────────▼───────────────────┐
│  OpenAICompatibleClient   │   │  ToolRegistry               │
│  (httpx, any /v1 host)    │   │  • execute_bash_command     │
└───────────────────────────┘   │  • view_workspace_file      │
                                │  • write_workspace_file     │
                                │  • browse_web_content       │
                                └─────────────────────────────┘
```

### Package layout

```
opencode_harness/
  cli.py                 # Entry point, slash commands, REPL
  config.py              # YAML/JSON + env loading
  models.py              # Message / ToolCall / ToolSpec types
  provider/
    client.py            # OpenAI-compatible HTTP client
  tools/
    registry.py          # Rigid ToolRegistry + extension API
    bash.py              # subprocess + timeout
    safety.py            # Destructive-command patterns
    files.py             # Workspace-bound file I/O
    web.py               # httpx + BeautifulSoup text extract
  agent/
    loop.py              # Multi-turn tool evaluation loop
    prompts.py           # System prompt builder
  ui/
    console.py           # Rich panels, spinners, confirmations
```

---

## Configuration

**Path:** `~/.opencode_harness/config.yaml` (or `.json`)

| Key | Default | Description |
|-----|---------|-------------|
| `provider.base_url` | `https://gen.pollinations.ai/v1` | OpenAI-compatible API root |
| `provider.model` | `kimi` | Active model id |
| `provider.api_key` | `""` | Prefer env vars instead |
| `tools.bash_timeout` | `45` | Seconds before kill |
| `tools.max_tool_rounds` | `12` | Circuit breaker |
| `tools.enforce_workspace_boundary` | `true` | Block writes outside CWD/workspace |
| `workspace` | process CWD | Root for bash + files |

### Environment variables

| Variable | Purpose |
|----------|---------|
| `POLLINATIONS_API_KEY` | API key (preferred for Pollinations) |
| `OPENAI_API_KEY` | Fallback key name |
| `OPENCODE_HARNESS_API_KEY` | Explicit harness key |
| `OPENCODE_HARNESS_BASE_URL` | Override base URL |
| `OPENCODE_HARNESS_MODEL` | Override model |
| `OPENCODE_HARNESS_CONFIG` | Config file path |
| `OPENCODE_HARNESS_WORKSPACE` | Workspace root |

---

## Built-in tools (OpenCode / Hermes-style)

Coding-agent toolbelt (not chat-only). Design reviewed against MIT-licensed
[OpenCode](https://github.com/anomalyco/opencode) and
[Hermes Agent](https://github.com/NousResearch/hermes-agent) — see `THIRD_PARTY.md`.

| Tool | Purpose |
|------|---------|
| `read_file` | Open files with line numbers + `offset`/`limit` pagination |
| `edit_file` | Surgical old→new string replace (unique match) |
| `write_file` | Create / full rewrite |
| `glob_files` | Find paths by glob (`**/*.py`) |
| `grep_search` | Content search (ripgrep when available) |
| `list_directory` | List a folder |
| `execute_bash_command` | Shell (45s timeout; destructive cmds need `[y/N]`) |
| `browse_web_content` | Fetch docs as cleaned text |

**Modes** (OpenCode-like):

- `build` (default) — full tools  
- `plan` — read/search only (no write/edit/bash)  

```bash
# in session
/mode plan
/mode build
```

Config: `agent_mode: build` in `config.yaml`.

Legacy aliases still work: `view_workspace_file`, `write_workspace_file`.

### Extending tools

```python
from opencode_harness.models import ToolSpec, ToolParameter

registry.register(ToolSpec(
    name="my_custom_tool",
    description="Does something useful",
    parameters=[ToolParameter("query", "string", "Search query")],
    handler=lambda query: f"result for {query}",
))
```

---

## Agent loop & circuit breaker

1. User submits a high-level goal.
2. Harness sends messages + tool schemas to the provider (`stream=False` for tool turns).
3. On `tool_calls`: log intent → run local tool → append `{role: "tool", tool_call_id, content}` → loop.
4. On final text: render to the user and stop.
5. **Hard stop** after **12** sequential tool executions per prompt (configurable) so the agent cannot recurse forever.

---

## REPL slash commands

| Command | Action |
|---------|--------|
| `/help` | Show help |
| `/model [name]` | Show or switch model |
| `/models` | List configured models |
| `/tools` | List tool registry |
| `/reset` | Clear conversation history |
| `/config` | Show effective settings |
| `/workspace [path]` | Show/change workspace |
| `/exit` | Quit |

Input history is stored at `~/.opencode_harness/history` via **prompt_toolkit**.

---

## CLI flags

```
honey --init
honey --config ./my.yaml
honey --model deepseek
honey --base-url http://localhost:11434/v1
honey --workspace /path/to/project
honey "one-shot goal text"
```

---

## Development

```bash
pip install -e ".[dev]"
pytest -q
honey --help
python -m opencode_harness --help
```

---

## License

MIT — use freely as a standalone developer-agent framework.
