"""Prompt builders for each generation stage.

Centralized and plain-string (no template engine) so prompts are easy to read,
version, and unit-test. The stable, reusable context for a book is
``BookSpec.compact()``; per-stage builders wrap it with role + task instructions.
"""

from __future__ import annotations

from .models import DEPTH_PROFILES, BookSpec, ChapterPlan, Outline, Style


def style_directive(style: Style) -> str:
    if style is Style.scientific:
        return (
            "Write in a precise, academic register — like a well-edited textbook or "
            "official documentation: third person, defined terminology, structured and "
            "rigorous explanations, careful about claims. Still readable, never dry."
        )
    return (
        "Write in a warm, casual register: address the reader as 'you', use plain "
        "language, analogies, and concrete examples, with an encouraging tone — like a "
        "knowledgeable friend who explains things really well."
    )


# --------------------------------------------------------------------------- #
# Outline
# --------------------------------------------------------------------------- #


def outline_system(spec: BookSpec) -> str:
    prof = DEPTH_PROFILES[spec.depth]
    lo, hi = prof["sections_per_chapter"]
    return (
        "You are an expert curriculum designer and author. You are planning a single, "
        "coherent, personalized learning BOOK (not a generic syllabus) for one specific "
        "learner.\n\n"
        f"{style_directive(spec.style)}\n\n"
        "Rules:\n"
        f"- Produce between {prof['min_chapters']} and {prof['max_chapters']} chapters, "
        f"each with {lo}-{hi} sections.\n"
        "- Order chapters so each builds on the previous (prerequisites first); the book "
        "should read as one arc, not disconnected modules.\n"
        "- Calibrate depth and starting point to the learner's current level and prior "
        "knowledge. Honor must-cover and skip requests.\n"
        "- For each section, give 2-5 concrete `key_points` describing what it actually "
        "teaches — not vague labels.\n"
        "- `introduces`: short concept tags first defined in that chapter (used later to "
        "avoid re-explaining things).\n"
        "- Return ONLY data matching the provided schema."
    )


def outline_user(spec: BookSpec) -> str:
    return (
        "Design the book for this learner and request:\n\n"
        f"{spec.compact()}\n\n"
        "Produce the complete outline now."
    )


# --------------------------------------------------------------------------- #
# Chapter drafting
# --------------------------------------------------------------------------- #


def chapter_system(spec: BookSpec, outline: Outline) -> str:
    """Stable per-book prefix (cacheable): role, rules, learner context, full TOC."""
    toc = "\n".join(f"{i}. {ch.title}" for i, ch in enumerate(outline.chapters, start=1))
    return (
        "You are writing ONE chapter of a personalized learning book. "
        f"{style_directive(spec.style)}\n\n"
        "Requirements for the chapter:\n"
        "- Use Markdown. Use `##` for the planned sections and `###` for sub-parts. Do "
        "NOT add an H1 title — the chapter title is added automatically.\n"
        "- Open with a short, specific motivation; avoid generic 'In this chapter we "
        "will...' filler.\n"
        "- Where the topic is technical, include at least one '### Worked example' with a "
        "fenced code block and a walk-through.\n"
        "- Include a '### Exercises' section with 2-4 concrete hands-on tasks or a "
        "mini-project.\n"
        "- Include a '### Quiz' with 2-4 self-check questions, then a bold '**Answers:**' "
        "block.\n"
        "- Do NOT invent URLs, citations, or a 'Further reading' list — verified "
        "resources are attached in a separate step.\n"
        "- Write for THIS learner's level and goals; be concrete, not vague.\n\n"
        "LEARNER & BOOK:\n"
        f"{spec.compact()}\n\n"
        "FULL TABLE OF CONTENTS (for coherence):\n"
        f"{toc}"
    )


def chapter_user(chapter: ChapterPlan, recap: str, already_introduced: list[str]) -> str:
    objectives = "\n".join(f"- {o}" for o in chapter.learning_objectives) or "- (none specified)"
    section_lines: list[str] = []
    for s in chapter.sections:
        section_lines.append(f"## {s.title}")
        section_lines.extend(f"   - {kp}" for kp in s.key_points)
    target = sum(s.target_words for s in chapter.sections)

    blocks = [
        f'Write the chapter titled "{chapter.title}".',
        "",
        "Learning objectives:",
        objectives,
        "",
        "Sections to cover (use these exact titles as your `##` headings):",
        "\n".join(section_lines),
    ]
    if recap:
        blocks += ["", recap]
    if already_introduced:
        blocks += [
            "",
            "Already explained in earlier chapters — reference briefly, do NOT re-teach "
            "from scratch: " + ", ".join(already_introduced),
        ]
    blocks += ["", f"Target length: about {target:,} words. Write the complete chapter in Markdown now."]
    return "\n".join(blocks)


# --------------------------------------------------------------------------- #
# Resource gathering (provenance-first: the model writes queries / picks indices,
# never URLs)
# --------------------------------------------------------------------------- #


def resource_queries_system() -> str:
    return (
        "You generate web SEARCH QUERIES used to find high-quality learning resources. "
        "Output ONLY search-query strings — never URLs, never invented links."
    )


def resource_queries_user(spec: BookSpec, chapter: ChapterPlan) -> str:
    points = "; ".join(kp for s in chapter.sections for kp in s.key_points[:2])
    return (
        f"Book topic: {spec.topic}\n"
        f"Chapter: {chapter.title}\n"
        f"Key points: {points}\n\n"
        "Write 2-3 focused search queries that would surface excellent, current learning "
        "resources (official docs, courses, tutorials, books, videos) for THIS chapter. "
        "Return only the queries."
    )


def resource_rank_system() -> str:
    return (
        "You curate learning resources. You are given a NUMBERED list of real candidate "
        "resources that have already been verified to exist. Select the best, most relevant, "
        "and diverse ones for the chapter. You may ONLY choose from the provided list by its "
        "index — never invent or modify URLs."
    )


def resource_rank_user(spec: BookSpec, chapter: ChapterPlan, candidates: str, max_results: int) -> str:
    return (
        f"Book topic: {spec.topic}\n"
        f"Chapter: {chapter.title}\n\n"
        f"Candidates:\n{candidates}\n\n"
        f"Choose up to {max_results} of the best, most relevant resources for this chapter. "
        "Prefer a mix of kinds (doc, course, article, video, book, repo). Return the selected "
        "indices, each with a 'kind' label."
    )
