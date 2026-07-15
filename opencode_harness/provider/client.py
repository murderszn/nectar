"""
HTTP client for OpenAI-compatible chat completions APIs.

Works with Pollinations (`https://gen.pollinations.ai/v1`), Ollama
(`http://localhost:11434/v1`), vLLM, LM Studio, and any other endpoint
that implements `/v1/chat/completions`.
"""

from __future__ import annotations

import json
import time
from typing import Any, Iterator, Optional

import httpx

from opencode_harness.config import ProviderConfig
from opencode_harness.logging_setup import get_logger
from opencode_harness.models import ChatChoice, ChatCompletion, Message, message_from_api

log = get_logger("provider")


class ProviderError(RuntimeError):
    """Raised when the remote model endpoint returns an error or bad payload."""

    def __init__(self, message: str, *, status_code: Optional[int] = None, body: str = ""):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class OpenAICompatibleClient:
    """
    Thin, dependency-light client.

    Design notes:
    - Tool-calling turns use non-streaming requests so tool_calls parse reliably.
    - Final assistant text can optionally stream for better UX.
    - No vendor SDK lock-in — only httpx + the OpenAI REST shape.
    """

    def __init__(self, config: ProviderConfig, api_key: str = ""):
        self.config = config
        self.api_key = api_key
        self._client = httpx.Client(
            base_url=config.base_url.rstrip("/"),
            timeout=httpx.Timeout(config.timeout, connect=30.0),
            headers=self._build_headers(),
        )

    def _build_headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "OpenCodeHarness/0.1",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "OpenAICompatibleClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _build_body(
        self,
        messages: list[Message],
        tools: Optional[list[dict[str, Any]]],
        *,
        stream: bool,
        model: Optional[str] = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": model or self.config.model,
            "messages": [m.to_api_dict() for m in messages],
            "temperature": self.config.temperature,
            "stream": stream,
        }
        if self.config.max_tokens is not None:
            body["max_tokens"] = self.config.max_tokens
        if tools:
            body["tools"] = tools
            # Encourage native tool use when the provider supports it
            body["tool_choice"] = "auto"
        return body

    def chat(
        self,
        messages: list[Message],
        tools: Optional[list[dict[str, Any]]] = None,
        *,
        model: Optional[str] = None,
    ) -> ChatCompletion:
        """Non-streaming chat completion (preferred for tool-call turns)."""
        body = self._build_body(messages, tools, stream=False, model=model)
        model_id = body.get("model")
        log.info(
            "POST %s/chat/completions  model=%s  msgs=%d  tools=%s  stream=false",
            self.config.base_url.rstrip("/"),
            model_id,
            len(messages),
            bool(tools),
        )
        t0 = time.monotonic()
        try:
            resp = self._client.post("/chat/completions", json=body)
        except httpx.TimeoutException as exc:
            log.error("provider timeout after %.1fs (limit=%ss)", time.monotonic() - t0, self.config.timeout)
            raise ProviderError(f"Request timed out after {self.config.timeout}s") from exc
        except httpx.HTTPError as exc:
            log.error("provider transport error: %s", exc)
            raise ProviderError(f"HTTP transport error: {exc}") from exc

        if resp.status_code >= 400:
            log.error("provider HTTP %s: %s", resp.status_code, resp.text[:400])
            raise ProviderError(
                f"Provider returned HTTP {resp.status_code}: {resp.text[:800]}",
                status_code=resp.status_code,
                body=resp.text,
            )

        try:
            data = resp.json()
        except json.JSONDecodeError as exc:
            log.error("provider non-JSON body: %s", resp.text[:200])
            raise ProviderError(f"Non-JSON response: {resp.text[:400]}") from exc

        log.info(
            "provider OK  HTTP %s  %.1fs  usage=%s",
            resp.status_code,
            time.monotonic() - t0,
            data.get("usage") or {},
        )
        return self._parse_completion(data)

    def chat_stream(
        self,
        messages: list[Message],
        tools: Optional[list[dict[str, Any]]] = None,
        *,
        model: Optional[str] = None,
    ) -> Iterator[str]:
        """
        Stream assistant content deltas (text only).

        Yields content string chunks. Tool-call streams should use
        `chat_collect` instead, which assembles the full Message.
        """
        msg = self.chat_collect(messages, tools=tools, model=model)
        if msg.tool_calls:
            raise _StreamHasToolCalls()
        if msg.content:
            yield msg.content

    def chat_collect(
        self,
        messages: list[Message],
        tools: Optional[list[dict[str, Any]]] = None,
        *,
        model: Optional[str] = None,
        on_text_delta: Optional[Any] = None,
        stream: bool = False,
    ) -> Message:
        """
        Request a completion and return a fully assembled assistant Message.

        When `stream=True`, content deltas are pushed to `on_text_delta` as
        they arrive (ideal for final user-facing prose). Tool-call argument
        fragments are assembled offline without streaming partial JSON to the UI.

        Falls back to non-streaming if the provider rejects stream mode.
        """
        if not stream:
            return self.chat(messages, tools=tools, model=model).first_message

        body = self._build_body(messages, tools, stream=True, model=model)
        content_parts: list[str] = []
        # tool index -> {id, name, arguments}
        tool_acc: dict[int, dict[str, str]] = {}
        saw_tool_calls = False

        try:
            with self._client.stream("POST", "/chat/completions", json=body) as resp:
                if resp.status_code >= 400:
                    err_text = resp.read().decode("utf-8", errors="replace")
                    # Some gateways reject stream+tools; fall back once
                    if resp.status_code in {400, 404, 422, 501}:
                        return self.chat(messages, tools=tools, model=model).first_message
                    raise ProviderError(
                        f"Provider returned HTTP {resp.status_code}: {err_text[:800]}",
                        status_code=resp.status_code,
                        body=err_text,
                    )
                for line in resp.iter_lines():
                    if not line:
                        continue
                    if line.startswith("data:"):
                        payload = line[5:].strip()
                    else:
                        payload = line.strip()
                    if not payload:
                        continue
                    if payload == "[DONE]":
                        break
                    try:
                        chunk = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    # Full message form (some proxies)
                    if "message" in choices[0] and not delta:
                        return message_from_api(choices[0]["message"])

                    piece = delta.get("content")
                    if piece:
                        content_parts.append(piece)
                        # Only stream text to UI when we have not seen tool_calls
                        if on_text_delta and not saw_tool_calls:
                            on_text_delta(piece)

                    for tc_delta in delta.get("tool_calls") or []:
                        saw_tool_calls = True
                        idx = int(tc_delta.get("index") or 0)
                        slot = tool_acc.setdefault(
                            idx, {"id": "", "name": "", "arguments": ""}
                        )
                        if tc_delta.get("id"):
                            slot["id"] = str(tc_delta["id"])
                        fn = tc_delta.get("function") or {}
                        if fn.get("name"):
                            slot["name"] = str(fn["name"])
                        if fn.get("arguments"):
                            slot["arguments"] += str(fn["arguments"])
        except httpx.TimeoutException as exc:
            raise ProviderError(f"Stream timed out after {self.config.timeout}s") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"HTTP transport error: {exc}") from exc

        from opencode_harness.models import ToolCall, ToolCallFunction

        tool_calls = None
        if tool_acc:
            tool_calls = [
                ToolCall(
                    id=tool_acc[i]["id"] or f"call_{i}",
                    type="function",
                    function=ToolCallFunction(
                        name=tool_acc[i]["name"],
                        arguments=tool_acc[i]["arguments"] or "{}",
                    ),
                )
                for i in sorted(tool_acc.keys())
            ]

        return Message(
            role="assistant",
            content="".join(content_parts) if content_parts else None,
            tool_calls=tool_calls,
        )

    def chat_auto(
        self,
        messages: list[Message],
        tools: Optional[list[dict[str, Any]]] = None,
        *,
        model: Optional[str] = None,
        prefer_stream: bool = False,
        on_text_delta: Optional[Any] = None,
    ) -> Message:
        """
        High-level helper used by the agent loop.

        Prefer non-streaming for tool-heavy turns (reliable). When
        prefer_stream is set, stream content deltas for final prose.
        """
        # Default: non-stream for tools (most reliable across providers)
        if tools and not prefer_stream:
            completion = self.chat(messages, tools=tools, model=model)
            return completion.first_message

        return self.chat_collect(
            messages,
            tools=tools,
            model=model,
            on_text_delta=on_text_delta,
            stream=prefer_stream,
        )

    @staticmethod
    def _parse_completion(data: dict[str, Any]) -> ChatCompletion:
        choices_raw = data.get("choices") or []
        choices: list[ChatChoice] = []
        for ch in choices_raw:
            msg_data = ch.get("message") or {}
            choices.append(
                ChatChoice(
                    message=message_from_api(msg_data),
                    finish_reason=ch.get("finish_reason"),
                )
            )
        return ChatCompletion(
            id=str(data.get("id") or ""),
            model=str(data.get("model") or ""),
            choices=choices,
            usage=dict(data.get("usage") or {}),
        )


class _StreamHasToolCalls(Exception):
    """Internal signal: streaming response included tool_calls."""
