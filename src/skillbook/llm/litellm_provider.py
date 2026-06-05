"""LiteLLM-backed provider — the one place that imports ``litellm``.

Wrapping LiteLLM behind :class:`~skillbook.llm.base.LLMProvider` keeps the rest of
the codebase provider-agnostic and makes swapping to native SDKs a one-file change.
"""

from __future__ import annotations

import json

import litellm

from .base import Completion, Message, Usage

# Be forgiving of provider-specific params and quiet by default.
litellm.drop_params = True
litellm.suppress_debug_info = True
# Helps Anthropic structured output (research note).
litellm.enable_json_schema_validation = True

# Map each provider's finish/stop reason onto our normalized vocabulary.
_FINISH_MAP = {
    "length": "max_tokens",
    "max_tokens": "max_tokens",
    "model_length": "max_tokens",
    "stop": "stop",
    "end_turn": "stop",
    "stop_sequence": "stop",
    "tool_calls": "stop",
    "tool_use": "stop",
    "content_filter": "error",
    None: "stop",
}


def _norm_stop(reason: str | None) -> str:
    return _FINISH_MAP.get(reason, reason or "stop")


def _loads_lenient(text: str) -> dict:
    """Parse JSON, tolerating prose or code fences around the object."""
    text = (text or "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        return json.loads(text[start : end + 1])
    raise ValueError("Model did not return valid JSON")


class LiteLLMProvider:
    def __init__(self, model: str) -> None:
        self.model = model

    # -- message assembly ---------------------------------------------------- #

    def _is_anthropic(self) -> bool:
        return self.model.startswith("anthropic") or self.model.startswith("claude")

    def _messages(self, system: str, messages: list[Message], cacheable_system: bool) -> list[Message]:
        if cacheable_system and self._is_anthropic():
            sys_msg: Message = {
                "role": "system",
                "content": [
                    {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
                ],
            }
        else:
            sys_msg = {"role": "system", "content": system}
        return [sys_msg, *messages]

    # -- usage / cost -------------------------------------------------------- #

    def _usage_from_response(self, resp) -> Usage:
        u = getattr(resp, "usage", None)
        it = int(getattr(u, "prompt_tokens", 0) or 0)
        ot = int(getattr(u, "completion_tokens", 0) or 0)
        cost = 0.0
        try:
            hidden = getattr(resp, "_hidden_params", {}) or {}
            cost = hidden.get("response_cost") or 0.0
            if not cost:
                cost = litellm.completion_cost(completion_response=resp) or 0.0
        except Exception:
            cost = 0.0
        return Usage(it, ot, float(cost or 0.0))

    def _cost_from_tokens(self, it: int, ot: int) -> float:
        try:
            prompt_cost, completion_cost = litellm.cost_per_token(
                model=self.model, prompt_tokens=it, completion_tokens=ot
            )
            return float((prompt_cost or 0.0) + (completion_cost or 0.0))
        except Exception:
            return 0.0

    # -- API ----------------------------------------------------------------- #

    def complete(self, system, messages, *, max_tokens, temperature=0.7, cacheable_system=False):
        resp = litellm.completion(
            model=self.model,
            messages=self._messages(system, messages, cacheable_system),
            max_tokens=max_tokens,
            temperature=temperature,
            num_retries=3,
        )
        choice = resp.choices[0]
        return Completion(
            text=choice.message.content or "",
            stop_reason=_norm_stop(choice.finish_reason),
            usage=self._usage_from_response(resp),
        )

    def stream_complete(
        self, system, messages, *, max_tokens, temperature=0.7, cacheable_system=False, on_delta=None
    ):
        stream = litellm.completion(
            model=self.model,
            messages=self._messages(system, messages, cacheable_system),
            max_tokens=max_tokens,
            temperature=temperature,
            stream=True,
            stream_options={"include_usage": True},
            num_retries=3,
        )
        parts: list[str] = []
        finish: str | None = None
        final_usage = None
        for chunk in stream:
            try:
                choice = chunk.choices[0]
                delta = getattr(choice, "delta", None)
                piece = getattr(delta, "content", None) if delta else None
                if piece:
                    parts.append(piece)
                    if on_delta:
                        on_delta(piece)
                if getattr(choice, "finish_reason", None):
                    finish = choice.finish_reason
            except (IndexError, AttributeError):
                pass
            if getattr(chunk, "usage", None):
                final_usage = chunk.usage

        text = "".join(parts)
        it = int(getattr(final_usage, "prompt_tokens", 0) or 0)
        ot = int(getattr(final_usage, "completion_tokens", 0) or 0)
        return Completion(
            text=text,
            stop_reason=_norm_stop(finish),
            usage=Usage(it, ot, self._cost_from_tokens(it, ot)),
        )

    @staticmethod
    def _extract_json(resp) -> dict | None:
        """Pull a JSON object from a response, whether the model put it in message
        content (the usual path, incl. Anthropic tool-based structured output that
        LiteLLM merges into content) or left it in a structured-output tool call."""
        try:
            message = resp.choices[0].message
        except (IndexError, AttributeError):
            return None
        content = getattr(message, "content", None)
        if content:
            try:
                return _loads_lenient(content)
            except ValueError:
                pass
        for call in getattr(message, "tool_calls", None) or []:
            args = getattr(getattr(call, "function", None), "arguments", None)
            if args:
                try:
                    return _loads_lenient(args)
                except ValueError:
                    continue
        return None

    def complete_json(self, system, messages, *, schema, max_tokens, cacheable_system=False):
        resp = litellm.completion(
            model=self.model,
            messages=self._messages(system, messages, cacheable_system),
            max_tokens=max_tokens,
            num_retries=3,
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "skillbook_schema", "schema": schema},
            },
        )
        data = self._extract_json(resp)
        usage = self._usage_from_response(resp)
        if data is not None:
            return data, usage

        # Fallback: some provider/model combos don't surface structured output where we
        # can read it. Retry once asking for plain JSON, without response_format.
        plain_system = (
            f"{system}\n\nReturn ONLY a single valid JSON object matching the requested "
            "schema. No prose, no markdown fences."
        )
        retry = litellm.completion(
            model=self.model,
            messages=self._messages(plain_system, messages, cacheable_system),
            max_tokens=max_tokens,
            num_retries=3,
        )
        data = self._extract_json(retry)
        usage = usage + self._usage_from_response(retry)
        if data is None:
            raise ValueError("Model did not return valid JSON")
        return data, usage
