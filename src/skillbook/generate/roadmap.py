"""The visual roadmap — a Mermaid flowchart of how the chapters build on each other.

Generated deterministically from the outline (so it is *always* valid Mermaid, with
no parse-error risk and no extra LLM call). Richer, LLM-authored prerequisite graphs
are a 'Later' enhancement.
"""

from __future__ import annotations

from ..models import Outline


def _label(text: str) -> str:
    """Make a chapter title safe + plain-text inside a quoted Mermaid node label."""
    cleaned = (
        text.replace("&", "and")
        .replace("<", "(")
        .replace(">", ")")
        .replace('"', "'")
        .replace("[", "(")
        .replace("]", ")")
    )
    cleaned = " ".join(cleaned.split())
    return cleaned[:60]


def build_roadmap_mermaid(outline: Outline) -> str:
    chapters = outline.chapters
    lines = ["flowchart TD"]
    for i, ch in enumerate(chapters, start=1):
        lines.append(f'    C{i}["{i}. {_label(ch.title)}"]')
    for i in range(1, len(chapters)):
        lines.append(f"    C{i} --> C{i + 1}")
    return "\n".join(lines)
