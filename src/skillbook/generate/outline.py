"""Stage 1 — plan the table of contents with one structured (JSON-schema) call.

The model decides titles, objectives, sections, and key points; SkillBook owns the
mechanical bits (chapter ids, per-section word budgets from the depth tier) so the
model can't get those wrong.
"""

from __future__ import annotations

from ..llm import LLMProvider, Usage
from ..models import DEPTH_PROFILES, BookSpec, ChapterPlan, Outline, Section
from ..prompts import outline_system, outline_user

# Hand-written JSON schema (no $ref/$defs, so every provider handles it cleanly).
# `target_words` and chapter `id` are intentionally omitted — we set those ourselves.
OUTLINE_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "title": {"type": "string"},
        "subtitle": {"type": "string"},
        "chapters": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "title": {"type": "string"},
                    "learning_objectives": {"type": "array", "items": {"type": "string"}},
                    "sections": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "title": {"type": "string"},
                                "key_points": {"type": "array", "items": {"type": "string"}},
                            },
                            "required": ["title", "key_points"],
                        },
                    },
                    "introduces": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["title", "learning_objectives", "sections", "introduces"],
            },
        },
    },
    "required": ["title", "subtitle", "chapters"],
}


def build_outline(provider: LLMProvider, spec: BookSpec) -> tuple[Outline, Usage]:
    data, usage = provider.complete_json(
        outline_system(spec),
        [{"role": "user", "content": outline_user(spec)}],
        schema=OUTLINE_SCHEMA,
        max_tokens=6000,
    )
    return _coerce_outline(data, spec), usage


def _coerce_outline(data: dict, spec: BookSpec) -> Outline:
    """Turn the raw model dict into a validated Outline, filling mechanical fields."""
    section_words = DEPTH_PROFILES[spec.depth]["section_words"]
    chapters: list[ChapterPlan] = []
    for i, ch in enumerate(data.get("chapters", []), start=1):
        sections = [
            Section(
                title=str(s.get("title") or f"Section {j}"),
                key_points=[str(k) for k in (s.get("key_points") or [])],
                target_words=section_words,
            )
            for j, s in enumerate(ch.get("sections") or [], start=1)
        ]
        if not sections:
            sections = [Section(title="Overview", key_points=[], target_words=section_words)]
        chapters.append(
            ChapterPlan(
                id=f"ch{i:02d}",
                title=str(ch.get("title") or f"Chapter {i}"),
                learning_objectives=[str(o) for o in (ch.get("learning_objectives") or [])],
                sections=sections,
                introduces=[str(c) for c in (ch.get("introduces") or [])],
            )
        )
    if not chapters:
        raise ValueError("Outline generation returned no chapters")
    return Outline(
        title=str(data.get("title") or spec.topic),
        subtitle=str(data.get("subtitle") or ""),
        chapters=chapters,
    )


def format_toc(outline: Outline) -> str:
    """A readable plain-text table of contents for the approval gate."""
    lines = [outline.title]
    if outline.subtitle:
        lines.append(outline.subtitle)
    lines.append("")
    for i, ch in enumerate(outline.chapters, start=1):
        lines.append(f"{i}. {ch.title}")
        for s in ch.sections:
            lines.append(f"     - {s.title}")
    total_sections = sum(len(c.sections) for c in outline.chapters)
    est_words = total_sections * (outline.chapters[0].sections[0].target_words if outline.chapters else 0)
    lines.append("")
    lines.append(
        f"{len(outline.chapters)} chapters · {total_sections} sections · ~{est_words:,} words target"
    )
    return "\n".join(lines)
