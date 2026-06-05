"""The provider-agnostic LLM contract.

Everything in SkillBook talks to models through :class:`LLMProvider`. Concrete
implementations live alongside this file (``litellm_provider.py``); a
:class:`MockProvider` lets the whole pipeline run offline with no API spend.

Design notes baked in from research:

* No book fits in one call, so chapter prose is **streamed** and the caller must
  see ``stop_reason`` to detect truncation and continue.
* Anthropic structured output is requested with a **dict** JSON schema (a known
  LiteLLM quirk with raw Pydantic classes).
* A *cacheable* system prefix can be marked so Anthropic prompt-caching kicks in.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Protocol, runtime_checkable

# A callback invoked with each streamed text delta (e.g. to update a live view).
OnDelta = Callable[[str], None]

# A chat message: {"role": "user"|"assistant"|"system", "content": str | list}
Message = dict[str, Any]


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.cost_usd + other.cost_usd,
        )


@dataclass(frozen=True)
class Completion:
    text: str
    stop_reason: str  # normalized: "stop" | "max_tokens" | "error"
    usage: Usage

    @property
    def truncated(self) -> bool:
        """True when the model hit the output cap mid-generation (continue from here)."""
        return self.stop_reason == "max_tokens"


@runtime_checkable
class LLMProvider(Protocol):
    """A minimal, stream-first, multi-provider chat interface."""

    model: str

    def complete(
        self,
        system: str,
        messages: list[Message],
        *,
        max_tokens: int,
        temperature: float = 0.7,
        cacheable_system: bool = False,
    ) -> Completion: ...

    def stream_complete(
        self,
        system: str,
        messages: list[Message],
        *,
        max_tokens: int,
        temperature: float = 0.7,
        cacheable_system: bool = False,
        on_delta: OnDelta | None = None,
    ) -> Completion: ...

    def complete_json(
        self,
        system: str,
        messages: list[Message],
        *,
        schema: dict,
        max_tokens: int,
        cacheable_system: bool = False,
    ) -> tuple[dict, Usage]: ...


# --------------------------------------------------------------------------- #
# Offline mock provider — drives the full pipeline + PDF render with no network
# --------------------------------------------------------------------------- #


def fake_from_schema(schema: dict, depth: int = 0) -> Any:
    """Build a minimal value that satisfies a JSON schema (for offline testing)."""
    if "enum" in schema and schema["enum"]:
        return schema["enum"][0]
    if "const" in schema:
        return schema["const"]
    if "anyOf" in schema:
        return fake_from_schema(schema["anyOf"][0], depth + 1)
    if "oneOf" in schema:
        return fake_from_schema(schema["oneOf"][0], depth + 1)

    t = schema.get("type")
    if isinstance(t, list):
        t = next((x for x in t if x != "null"), "string")

    if t == "object":
        props = schema.get("properties", {})
        out: dict[str, Any] = {}
        for key, sub in props.items():
            out[key] = fake_from_schema(sub, depth + 1)
        return out
    if t == "array":
        item = schema.get("items", {"type": "string"})
        count = 2 if depth < 4 else 1
        return [fake_from_schema(item, depth + 1) for _ in range(count)]
    if t == "integer":
        return schema.get("default", 3)
    if t == "number":
        return schema.get("default", 1.0)
    if t == "boolean":
        return schema.get("default", True)
    if t == "null":
        return None
    return schema.get("default", schema.get("title", "Sample"))


def _mock_markdown(system: str, messages: list[Message]) -> str:
    """Produce a well-structured placeholder chapter so PDF rendering is exercised."""
    hint = "this topic"
    for msg in messages:
        content = msg.get("content")
        if not isinstance(content, str):
            continue
        if "TITLE:" in content:
            hint = content.split("TITLE:", 1)[1].splitlines()[0].strip() or hint
            break
        if 'titled "' in content:
            hint = content.split('titled "', 1)[1].split('"', 1)[0].strip() or hint
            break
    return (
        f"This chapter explores **{hint}** from first principles, building intuition "
        "before formalism. We motivate each idea with a concrete scenario, then connect "
        "it back to what you already know.\n\n"
        "## Core idea\n\n"
        "The central concept can be understood as a mapping from inputs to outcomes. "
        "Consider a simple analogy: a recipe transforms ingredients into a dish, where "
        "each step constrains what is possible next.\n\n"
        "## Going deeper\n\n"
        "Once the basics click, the interesting questions are about trade-offs. There is "
        "rarely one right answer — there are answers that fit a context.\n\n"
        "### Worked example\n\n"
        "```python\n"
        "def example(values):\n"
        "    return sum(v * v for v in values)\n\n"
        "print(example([1, 2, 3]))  # 14\n"
        "```\n\n"
        "Walking through it: each value is squared, then the squares are summed.\n\n"
        "### Exercises\n\n"
        "1. Re-implement the example without a comprehension.\n"
        "2. Extend it to ignore negative inputs.\n"
        "3. Explain when this approach breaks down.\n\n"
        "### Quiz\n\n"
        "1. What does the function return for `[2, 2]`?\n"
        "2. Why might squaring be useful here?\n\n"
        "**Answers:** 1) `8`. 2) Squaring emphasizes larger values and removes signs.\n"
    )


class MockProvider:
    """A deterministic, offline provider for dry-runs and tests."""

    def __init__(self, model: str = "mock/mock") -> None:
        self.model = model

    def complete(self, system, messages, *, max_tokens, temperature=0.7, cacheable_system=False):
        text = _mock_markdown(system, messages)
        return Completion(text=text, stop_reason="stop", usage=Usage(120, len(text) // 4, 0.0))

    def stream_complete(
        self, system, messages, *, max_tokens, temperature=0.7, cacheable_system=False, on_delta=None
    ):
        text = _mock_markdown(system, messages)
        if on_delta:
            step = 24
            for i in range(0, len(text), step):
                on_delta(text[i : i + step])
        return Completion(text=text, stop_reason="stop", usage=Usage(120, len(text) // 4, 0.0))

    def complete_json(self, system, messages, *, schema, max_tokens, cacheable_system=False):
        return fake_from_schema(schema), Usage(90, 400, 0.0)
