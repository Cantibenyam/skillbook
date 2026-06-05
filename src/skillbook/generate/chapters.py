"""Stage 2 — draft each chapter sequentially, streaming, truncation-safe.

A book never fits in one model call, so each chapter is streamed with a generous
per-call cap; if the model hits that cap mid-chapter we feed the partial back and
continue. Continuity comes from a lightweight deterministic recap of prior chapters
(titles + objectives) plus an anti-repetition list of already-introduced concepts —
not the heavier running-summary/ledger machinery (that's a 'Later' feature).
"""

from __future__ import annotations

from ..llm import LLMProvider, OnDelta, Usage
from ..models import BookSpec, ChapterDraft, ChapterPlan, Outline
from ..prompts import chapter_system, chapter_user

# A safe per-call output cap (well under every provider's max), with continuation
# to assemble longer chapters across calls.
PER_CALL_MAX_TOKENS = 8000
MAX_CONTINUATIONS = 3


def build_recap(prior_chapters: list[ChapterPlan]) -> tuple[str, list[str]]:
    """Return (recap_text, already_introduced_concepts) for continuity + anti-repetition."""
    if not prior_chapters:
        return "", []
    lines: list[str] = []
    introduced: list[str] = []
    for i, ch in enumerate(prior_chapters, start=1):
        objective = ch.learning_objectives[0] if ch.learning_objectives else ""
        suffix = f": {objective}" if objective else ""
        lines.append(f'- Ch{i} "{ch.title}"{suffix}')
        introduced.extend(ch.introduces)
    recap = "The book so far (already covered — build on it, don't repeat):\n" + "\n".join(lines)
    # De-duplicate while preserving order.
    seen: set[str] = set()
    unique = [c for c in introduced if not (c in seen or seen.add(c))]
    return recap, unique


def draft_chapter(
    provider: LLMProvider,
    spec: BookSpec,
    outline: Outline,
    chapter: ChapterPlan,
    recap: str,
    already_introduced: list[str],
    *,
    on_delta: OnDelta | None = None,
    on_warn: OnDelta | None = None,
) -> tuple[ChapterDraft, Usage]:
    system = chapter_system(spec, outline)
    messages = [{"role": "user", "content": chapter_user(chapter, recap, already_introduced)}]

    parts: list[str] = []
    total = Usage()
    completion = None
    for _ in range(MAX_CONTINUATIONS + 1):
        completion = provider.stream_complete(
            system,
            messages,
            max_tokens=PER_CALL_MAX_TOKENS,
            temperature=0.7,
            cacheable_system=True,
            on_delta=on_delta,
        )
        parts.append(completion.text)
        total = total + completion.usage
        if not completion.truncated:
            break
        # Continue from the partial text.
        messages.append({"role": "assistant", "content": completion.text})
        messages.append(
            {"role": "user", "content": "Continue exactly where you left off. Do not repeat earlier text."}
        )

    # Exhausting the continuation cap while still truncated means the chapter is clipped.
    if completion is not None and completion.truncated and on_warn:
        on_warn(f"Chapter '{chapter.title}' hit the generation cap and may be cut off.")

    markdown = "".join(parts).strip()
    return ChapterDraft(id=chapter.id, title=chapter.title, markdown=markdown), total
