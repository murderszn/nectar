"""
Multi-turn tool-evaluation loop with a hard circuit breaker.

Flow:
  user goal → messages + tool schemas → model
    → if tool_calls: execute locally, append role=tool, loop
    → if final text: stream/print to user, break

Maximum sequential tool executions per user prompt: configurable
(default 12) via ToolConfig.max_tool_rounds.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from opencode_harness.agent.prompts import build_system_prompt
from opencode_harness.config import AppConfig
from opencode_harness.logging_setup import get_logger
from opencode_harness.models import Message, ToolCall
from opencode_harness.provider.client import OpenAICompatibleClient, ProviderError
from opencode_harness.tools.registry import ToolRegistry

log = get_logger("agent")


class CircuitBreakerTripped(RuntimeError):
    """Raised when the agent exceeds max sequential tool rounds."""


@dataclass
class LoopResult:
    """Outcome of one user-turn agent run."""

    final_text: str
    tool_rounds: int
    messages: list[Message] = field(default_factory=list)
    stopped_reason: str = "completed"  # completed | circuit_breaker | error


# UI callbacks — keep the loop free of Rich so it is testable headlessly
OnToolStart = Callable[[ToolCall, dict[str, Any]], None]
OnToolEnd = Callable[[ToolCall, str], None]
OnAssistantText = Callable[[str], None]
OnStatus = Callable[[str], None]
OnStreamDelta = Callable[[str], None]


class AgentLoop:
    """
    Stateful multi-turn conversation manager.

    Message history persists across `run()` calls so the CLI can hold a
    continuous session. Call `reset()` to start fresh while keeping config.
    """

    def __init__(
        self,
        config: AppConfig,
        client: OpenAICompatibleClient,
        registry: ToolRegistry,
        *,
        on_tool_start: Optional[OnToolStart] = None,
        on_tool_end: Optional[OnToolEnd] = None,
        on_assistant_text: Optional[OnAssistantText] = None,
        on_status: Optional[OnStatus] = None,
        on_stream_delta: Optional[OnStreamDelta] = None,
    ):
        self.config = config
        self.client = client
        self.registry = registry
        self.on_tool_start = on_tool_start
        self.on_tool_end = on_tool_end
        self.on_assistant_text = on_assistant_text
        self.on_status = on_status
        self.on_stream_delta = on_stream_delta
        self.messages: list[Message] = []
        self._bootstrap_system()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Clear history and re-seed the system prompt."""
        self.messages.clear()
        self._bootstrap_system()

    def set_model(self, model: str) -> None:
        self.config.provider.model = model
        # Refresh system prompt so the model name stays accurate
        if self.messages and self.messages[0].role == "system":
            self.messages[0] = Message(role="system", content=self._system_text())
        else:
            self._bootstrap_system()

    def run(self, user_input: str) -> LoopResult:
        """
        Execute one user goal through the tool loop.

        Returns LoopResult; does not raise on circuit breaker — sets
        stopped_reason instead (still re-raises ProviderError for API issues).
        """
        if not user_input or not user_input.strip():
            return LoopResult(final_text="", tool_rounds=0, messages=self.messages, stopped_reason="empty")

        preview = user_input.strip().replace("\n", " ")
        if len(preview) > 120:
            preview = preview[:117] + "…"
        log.info("▶ user goal: %s", preview)

        self.messages.append(Message(role="user", content=user_input.strip()))
        tools = self.registry.openai_tools()
        max_rounds = max(1, self.config.tools.max_tool_rounds)
        tool_executions = 0
        turn = 0
        run_started = time.monotonic()

        # After tool rounds we may stream the final prose turn for better UX.
        # First turns (and any turn that might emit tool_calls) stay non-stream
        # by default — OpenAI-compatible tool streaming is provider-fragile.
        stream_final = bool(self.config.provider.stream_final)

        while True:
            turn += 1
            self._status(f"Consulting model… (turn {turn})")
            log.info(
                "⟳ model request  turn=%d  model=%s  messages=%d  tools=%d",
                turn,
                self.config.provider.model,
                len(self.messages),
                len(tools or []),
            )
            streamed_to_ui = False
            t0 = time.monotonic()
            try:
                # Non-streaming for tool-capable turns: reliable tool_calls JSON.
                # If the model returns pure text, we still render it below.
                prefer_stream = stream_final and tool_executions > 0 and bool(self.on_stream_delta)

                def _delta(chunk: str) -> None:
                    nonlocal streamed_to_ui
                    streamed_to_ui = True
                    if self.on_stream_delta:
                        self.on_stream_delta(chunk)

                if prefer_stream:
                    log.debug("model request mode=stream")
                    assistant = self.client.chat_collect(
                        self.messages,
                        tools=tools if tools else None,
                        model=self.config.provider.model,
                        on_text_delta=_delta,
                        stream=True,
                    )
                    # If the stream actually emitted tool_calls, ignore partial text UI
                    if assistant.tool_calls:
                        streamed_to_ui = False
                else:
                    log.debug("model request mode=blocking")
                    assistant = self.client.chat(
                        self.messages,
                        tools=tools if tools else None,
                        model=self.config.provider.model,
                    ).first_message
            except ProviderError as exc:
                log.error("model request failed after %.1fs: %s", time.monotonic() - t0, exc)
                raise

            elapsed = time.monotonic() - t0
            n_calls = len(assistant.tool_calls or [])
            content_len = len(assistant.content or "")
            log.info(
                "✓ model response  turn=%d  %.1fs  tool_calls=%d  content_chars=%d",
                turn,
                elapsed,
                n_calls,
                content_len,
            )

            # Persist assistant message (with tool_calls if any)
            self.messages.append(assistant)

            if assistant.tool_calls:
                # Circuit breaker counts each tool *call* toward the budget
                for tc in assistant.tool_calls:
                    if tool_executions >= max_rounds:
                        msg = (
                            f"Circuit breaker: reached max of {max_rounds} tool "
                            f"executions for this prompt. Stopping."
                        )
                        log.warning("circuit breaker tripped at %d tool executions", tool_executions)
                        self._status(msg)
                        if self.on_assistant_text:
                            self.on_assistant_text(msg)
                        return LoopResult(
                            final_text=msg,
                            tool_rounds=tool_executions,
                            messages=list(self.messages),
                            stopped_reason="circuit_breaker",
                        )

                    tool_executions += 1
                    result_text = self._execute_one(tc)
                    self.messages.append(
                        Message(
                            role="tool",
                            content=result_text,
                            tool_call_id=tc.id,
                            name=tc.function.name,
                        )
                    )
                # Loop: send updated history back to the model
                continue

            # Final text response
            final = (assistant.content or "").strip()
            if final:
                if not streamed_to_ui and self.on_assistant_text:
                    self.on_assistant_text(final)
                elif streamed_to_ui and self.on_stream_delta:
                    # Stream path already printed deltas; emit a trailing newline signal
                    self.on_stream_delta("\n")
            else:
                final = "(model returned empty content)"
                log.warning("model returned empty final content")
                if self.on_assistant_text:
                    self.on_assistant_text(final)

            total = time.monotonic() - run_started
            log.info(
                "■ goal complete  tools=%d  turns=%d  total=%.1fs",
                tool_executions,
                turn,
                total,
            )
            return LoopResult(
                final_text=final,
                tool_rounds=tool_executions,
                messages=list(self.messages),
                stopped_reason="completed",
            )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _bootstrap_system(self) -> None:
        self.messages = [Message(role="system", content=self._system_text())]

    def _system_text(self) -> str:
        mode = getattr(self.config, "agent_mode", "build") or "build"
        return build_system_prompt(
            self.config.workspace,
            model=self.config.provider.model,
            extra=self.config.system_prompt_extra,
            tool_names=self.registry.list_names(),
            mode=mode,
        )

    def _status(self, text: str) -> None:
        log.debug("status: %s", text)
        if self.on_status:
            self.on_status(text)

    def _execute_one(self, tc: ToolCall) -> str:
        name = tc.function.name
        try:
            args = tc.function.parsed_args()
        except ValueError as exc:
            err = f"ERROR: {exc}"
            log.error("tool %s bad args: %s", name, exc)
            if self.on_tool_start:
                self.on_tool_start(tc, {})
            if self.on_tool_end:
                self.on_tool_end(tc, err)
            return err

        arg_preview = _preview_args(name, args)
        log.info("⚙ tool start  %s  id=%s  %s", name, tc.id or "?", arg_preview)
        self._status(f"Running {name}…")

        if self.on_tool_start:
            self.on_tool_start(tc, args)

        t0 = time.monotonic()
        result = self.registry.dispatch(name, args)
        elapsed = time.monotonic() - t0

        outcome = "ok"
        if result.startswith("ERROR"):
            outcome = "error"
        elif result.startswith("BLOCKED"):
            outcome = "blocked"
        elif result.startswith("TIMEOUT"):
            outcome = "timeout"

        log.info(
            "↳ tool end    %s  %.2fs  outcome=%s  result_chars=%d",
            name,
            elapsed,
            outcome,
            len(result),
        )
        if outcome != "ok":
            log.warning("tool %s %s: %s", name, outcome, result[:300].replace("\n", " "))

        if self.on_tool_end:
            self.on_tool_end(tc, result)
        return result


def _preview_args(name: str, args: dict[str, Any]) -> str:
    """Compact one-line arg summary for logs (never dumps huge file bodies)."""
    if name == "execute_bash_command":
        cmd = str(args.get("command", ""))
        return f"command={cmd[:160]!r}" + ("…" if len(cmd) > 160 else "")
    if name in {
        "view_workspace_file",
        "write_workspace_file",
        "read_file",
        "write_file",
        "edit_file",
        "list_directory",
    }:
        path = args.get("path", "?")
        extra = ""
        if name in {"write_workspace_file", "write_file"}:
            extra = f" content_chars={len(str(args.get('content', '')))}"
        if name == "edit_file":
            extra = f" old_len={len(str(args.get('old_string', '')))}"
        if name == "read_file":
            extra = f" offset={args.get('offset', 1)} limit={args.get('limit', 400)}"
        return f"path={path!r}{extra}"
    if name == "glob_files":
        return f"pattern={args.get('pattern', '')!r} path={args.get('path', '.')!r}"
    if name == "grep_search":
        return f"pattern={args.get('pattern', '')!r} path={args.get('path', '.')!r}"
    if name == "browse_web_content":
        return f"url={args.get('url', '')!r}"
    flat = {k: (str(v)[:60] + "…" if len(str(v)) > 60 else v) for k, v in args.items()}
    return str(flat)

    def export_transcript(self) -> list[dict[str, Any]]:
        """JSON-serializable history for debugging / logging."""
        return [m.to_api_dict() for m in self.messages]
