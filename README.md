# 🍯 Nectar / Honey

> **Open coding agent for the terminal** — Claude/OpenCode-style session UX, full local toolbelt, and **Pollinations Pollen (BYOP)** as login/payment.

```bash
pip install opencode-harness
honey --init
honey login    # browser device code → enter.pollinations.ai
honey          # start interactive session
```

[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://python.org)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

---

## What is it?

**Honey** (`opencode-harness`) is a model-agnostic coding agent that runs in your terminal. It brings the **Claude Code / OpenCode** experience locally — with a scrollback chat interface, inline tool execution, and visual ASCII art chrome — while staying provider-agnostic via OpenAI-compatible APIs.

- **Interactive scrollback session** — no alt-screen takeover, terminal history stays usable
- **9 built-in tools** — read, edit, write, search, glob, bash, browse web
- **Circuit breaker** — hard limit on tool rounds so the agent can't recurse forever
- **5 visual themes** — rainbow, prism, pulse, honey, quiet
- **Pollinations BYOP auth** — device-code login, or bring your own API key
- **Local-first** — works with Ollama, LM Studio, vLLM out of the box

---

## Quick start

```bash
# 1. Install
pip install opencode-harness

# 2. Initialize config
honey --init

# 3. Log in (Pollinations BYOP — uses your balance)
honey login

# 4. Start an interactive session
honey

# 5. Or run one-shot
honey "Find all TODOs in this repo and summarize them"
```

---

## Providers

Any OpenAI-compatible endpoint works out of the box:

| Provider | Base URL | Model example |
|----------|----------|---------------|
| **Pollinations** (default) | `https://gen.pollinations.ai/v1` | `kimi`, `deepseek` |
| **Ollama** (local) | `http://localhost:11434/v1` | `hermes`, `llama3.1` |
| **LM Studio** | `http://localhost:1234/v1` | any loaded model |
| **vLLM / LiteLLM** | their `/v1` URL | any |

Switch provider via CLI flag or config:

```bash
honey --base-url http://localhost:11434/v1 --model hermes
```

Or edit `~/.opencode_harness/config.yaml`:

```yaml
provider:
  base_url: "http://localhost:11434/v1"
  api_key: "ollama"
  model: "hermes"
```

---

## Auth

| Command | Action |
|---------|--------|
| `honey login` | Device flow → browser → save key to `~/.opencode_harness/credentials.json` |
| `honey logout` | Clear stored credentials |
| `honey status` | Show endpoint, model, masked key source |

**Key resolution order:** `POLLINATIONS_API_KEY` env → `credentials.json` → `provider.api_key` in config → interactive prompt.

---

## Interactive session

Running `honey` opens a scrollback chat. Type a goal, watch tools run inline, read the answer.

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
| `/help` | Show commands |
| `/model <name>` | Switch model |
| `/reset` | Clear conversation history |
| `/tools` | List available tools |
| `/config` | Show effective settings |
| `/mode plan` | Read-only mode (no write/edit/bash) |
| `/mode build` | Full tools mode (default) |
| `Ctrl+C` | Clear current line |
| `Ctrl+D` or `/exit` | Quit |

Optional full-screen mode: `honey --tui`

---

## Built-in tools

| Tool | Purpose |
|------|---------|
| `read_file` | Open files with line numbers + pagination (`offset`/`limit`) |
| `edit_file` | Surgical old→new string replace (unique match) |
| `write_file` | Create or overwrite files |
| `glob_files` | Find paths by glob (`**/*.py`) |
| `grep_search` | Content search (ripgrep when available) |
| `list_directory` | List a folder |
| `execute_bash_command` | Shell with 45s timeout; destructive commands need `[y/N]` confirmation |
| `browse_web_content` | Fetch docs as cleaned text |

**Modes:**
- `build` (default) — full tool access
- `plan` — read/search only (no write/edit/bash)

---

## Themes

Set in `~/.opencode_harness/config.yaml` or via `/theme <name>` in session:

| Theme | Style |
|-------|-------|
| `rainbow` | Vivid rainbow bars + braille spinner (default) |
| `prism` | Spinning color circles + prism accents |
| `pulse` | Soft pastel pulse dots |
| `honey` | Warm nectar gradient |
| `quiet` | Minimal dim chrome |

---

## Activity logging

Every run writes a rotating log so you can see model calls, tool starts/ends, shell exit codes, and timings:

```bash
# Live tail while session runs
tail -f ~/.opencode_harness/logs/harness.log

# Dump recent lines
honey logs

# Mirror logs to stderr
honey -v
```

---

## Architecture

```
┌─────────────────────────────────────────────┐
│  CLI (prompt_toolkit + Rich panels/spinners) │
└───────────────────────┬─────────────────────┘
                        │ user goal
┌───────────────────────▼─────────────────────┐
│  AgentLoop                                    │
│   • system prompt + tool JSON schemas        │
│   • circuit breaker (max 12 tool rounds)     │
│   • append role=tool messages → re-query     │
└───────────────┬─────────────────┬─────────────┘
                │                 │
┌───────────────▼─────────┐ ┌─────▼─────────────┐
│  OpenAICompatibleClient │ │  ToolRegistry      │
│  (httpx, any /v1 host)  │ │  • bash, files,   │
└─────────────────────────┘ │    web, search    │
                            └───────────────────┘
```

---

## Configuration

**Path:** `~/.opencode_harness/config.yaml` (or `.json`)

```yaml
provider:
  base_url: "https://gen.pollinations.ai/v1"
  model: "kimi"
  api_key: ""              # prefer env vars

tools:
  bash_timeout: 45
  max_tool_rounds: 12
  enforce_workspace_boundary: true

ui:
  theme: rainbow
  syntax_theme: monokai
  show_tool_args: true

# workspace: "/absolute/path/to/project"
```

**Environment variables:**

| Variable | Purpose |
|----------|---------|
| `POLLINATIONS_API_KEY` | API key (preferred for Pollinations) |
| `OPENAI_API_KEY` | Fallback key |
| `OPENCODE_HARNESS_API_KEY` | Explicit harness key |
| `OPENCODE_HARNESS_BASE_URL` | Override base URL |
| `OPENCODE_HARNESS_MODEL` | Override model |
| `OPENCODE_HARNESS_CONFIG` | Config file path |
| `OPENCODE_HARNESS_WORKSPACE` | Workspace root |

---

## Development

```bash
git clone https://github.com/murderszn/nectar.git
cd nectar
pip install -e ".[dev]"
pytest -q
```

---

## License

MIT — see [LICENSE](LICENSE)
