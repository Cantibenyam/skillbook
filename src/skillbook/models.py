"""Core data models (Pydantic v2).

These are the shared contracts every stage of the pipeline reads and writes.
They are deliberately plain data — behaviour lives in the ``generate`` /
``resources`` / ``render`` packages.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field

from .config import DEFAULT_MODEL


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Style(str, Enum):
    """The writing register of the book — implemented downstream as a CSS theme swap."""

    casual = "casual"
    scientific = "scientific"


class Depth(str, Enum):
    primer = "primer"
    standard = "standard"
    comprehensive = "comprehensive"


# Depth -> generation targets. Steers the outline (chapter/section counts) and the
# per-section word budget that drives chapter length.
DEPTH_PROFILES: dict[Depth, dict] = {
    Depth.primer: {
        "min_chapters": 4,
        "max_chapters": 6,
        "section_words": 700,
        "sections_per_chapter": (2, 3),
    },
    Depth.standard: {
        "min_chapters": 7,
        "max_chapters": 10,
        "section_words": 1100,
        "sections_per_chapter": (3, 4),
    },
    Depth.comprehensive: {
        "min_chapters": 12,
        "max_chapters": 18,
        "section_words": 1400,
        "sections_per_chapter": (3, 5),
    },
}


class Profile(BaseModel):
    """The persistent learner profile, reused across every book."""

    name: str = ""
    background: str = ""
    current_level: str = "beginner"
    goals: list[str] = Field(default_factory=list)
    learning_style: str = ""
    time_budget: str = ""
    prior_knowledge: list[str] = Field(default_factory=list)
    preferred_style: Style = Style.casual
    language: str = "English"

    def compact(self) -> str:
        """A short, prompt-injectable rendering of the profile."""
        parts = [f"Name: {self.name or 'the learner'}"]
        if self.background:
            parts.append(f"Background: {self.background}")
        parts.append(f"Self-rated level: {self.current_level}")
        if self.goals:
            parts.append("Goals: " + "; ".join(self.goals))
        if self.learning_style:
            parts.append(f"Learning style: {self.learning_style}")
        if self.time_budget:
            parts.append(f"Time budget: {self.time_budget}")
        if self.prior_knowledge:
            parts.append("Already knows: " + ", ".join(self.prior_knowledge))
        parts.append(f"Language: {self.language}")
        return "\n".join(parts)


class BookSpec(BaseModel):
    """Everything needed to generate one book: profile + per-book interview + options."""

    topic: str
    profile: Profile = Field(default_factory=Profile)
    # Per-book interview answers (not persisted to the profile).
    already_known: str = ""
    outcome: str = ""
    must_cover: list[str] = Field(default_factory=list)
    must_skip: list[str] = Field(default_factory=list)
    constraints: str = ""
    depth: Depth = Depth.standard
    style: Style = Style.casual
    model: str = DEFAULT_MODEL

    def compact(self) -> str:
        """The stable prefix injected into every LLM call for this book."""
        lines = [
            f"TOPIC: {self.topic}",
            f"DEPTH: {self.depth.value}",
            f"REGISTER: {self.style.value}",
            "",
            "LEARNER PROFILE:",
            self.profile.compact(),
        ]
        book: list[str] = []
        if self.already_known:
            book.append(f"Already knows about this topic: {self.already_known}")
        if self.outcome:
            book.append(f"Desired outcome: {self.outcome}")
        if self.must_cover:
            book.append("Must cover: " + "; ".join(self.must_cover))
        if self.must_skip:
            book.append("Skip / de-emphasize: " + "; ".join(self.must_skip))
        if self.constraints:
            book.append(f"Constraints: {self.constraints}")
        if book:
            lines += ["", "THIS BOOK:"] + book
        return "\n".join(lines)


class Section(BaseModel):
    title: str
    key_points: list[str] = Field(default_factory=list)
    target_words: int = 1100


class ChapterPlan(BaseModel):
    """A chapter as planned in the outline (no prose yet)."""

    id: str
    title: str
    learning_objectives: list[str] = Field(default_factory=list)
    sections: list[Section] = Field(default_factory=list)
    # Lightweight concept tags introduced here — used for the recap, not a full ledger.
    introduces: list[str] = Field(default_factory=list)


class Outline(BaseModel):
    title: str
    subtitle: str = ""
    chapters: list[ChapterPlan] = Field(default_factory=list)


class Resource(BaseModel):
    """A verified external learning resource attached to a chapter."""

    title: str
    url: str
    source: str = "web"  # provenance: which provider returned it
    query: str = ""  # provenance: which search query surfaced it
    kind: str = "article"  # course | doc | book | article | video | repo
    snippet: str = ""
    status: str = "ok"  # ok | unverified  (unverified = reachable-but-bot-blocked)
    retrieved_at: str = Field(default_factory=utcnow_iso)


class ChapterDraft(BaseModel):
    """A fully generated chapter: prose (Markdown) + its verified resources."""

    id: str
    title: str
    markdown: str = ""
    resources: list[Resource] = Field(default_factory=list)


class RunState(BaseModel):
    """Persisted run state enabling checkpoint/resume of a long generation."""

    run_id: str
    created_at: str = Field(default_factory=utcnow_iso)
    # created | outline | drafting | drafted | resourced | done
    stage: str = "created"
    spec: BookSpec
    outline: Outline | None = None
    completed_chapter_ids: list[str] = Field(default_factory=list)
    out_path: str = ""
    # Running usage totals across all LLM calls in the run.
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
