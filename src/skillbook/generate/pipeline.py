"""The orchestrator: runs the stages, persists every artifact, and resumes.

Run layout (under ``<base_dir>/<run_id>/``)::

    run_state.json          # RunState — the resume checkpoint
    chapters/<id>.json      # each ChapterDraft as it completes
    book.html               # assembled HTML (render stage)

Resuming re-loads ``run_state.json`` and skips any chapter already marked complete,
so a crash at chapter 9/14 continues at 10.
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path

from ..config import Config, load_config
from ..llm import LLMProvider, Usage
from ..models import BookSpec, ChapterDraft, RunState
from .chapters import build_recap, draft_chapter
from .outline import build_outline


def _atomic_write_text(path: Path, text: str) -> None:
    """Write to a temp file then os.replace() it in — so a crash mid-write never
    leaves a truncated checkpoint that would brick resume."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


class Reporter:
    """Progress sink. The default is silent; the CLI supplies a Rich-backed one."""

    def stage(self, name: str, detail: str = "") -> None: ...
    def chapter_start(self, index: int, total: int, title: str) -> None: ...
    def chapter_delta(self, text: str) -> None: ...
    def chapter_done(self, index: int, total: int, title: str, usage: Usage) -> None: ...
    def info(self, msg: str) -> None: ...
    def warn(self, msg: str) -> None: ...


def slugify(text: str, maxlen: int = 40) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:maxlen].strip("-") or "book"


def new_run_id(topic: str) -> str:
    return f"{slugify(topic)}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"


class RunStore:
    """Filesystem persistence for one run."""

    def __init__(self, run_id: str, base_dir: str | Path = "runs") -> None:
        self.run_id = run_id
        self.dir = Path(base_dir) / run_id
        self.chapters_dir = self.dir / "chapters"

    def ensure(self) -> None:
        self.chapters_dir.mkdir(parents=True, exist_ok=True)

    @property
    def state_path(self) -> Path:
        return self.dir / "run_state.json"

    @property
    def html_path(self) -> Path:
        return self.dir / "book.html"

    def chapter_path(self, chapter_id: str) -> Path:
        return self.chapters_dir / f"{chapter_id}.json"

    def save_state(self, state: RunState) -> None:
        _atomic_write_text(self.state_path, state.model_dump_json(indent=2))

    def load_state(self) -> RunState:
        return RunState.model_validate_json(self.state_path.read_text(encoding="utf-8"))

    def save_chapter(self, draft: ChapterDraft) -> None:
        _atomic_write_text(self.chapter_path(draft.id), draft.model_dump_json(indent=2))

    def load_chapter(self, chapter_id: str) -> ChapterDraft:
        return ChapterDraft.model_validate_json(self.chapter_path(chapter_id).read_text(encoding="utf-8"))


def _add_usage(state: RunState, usage: Usage) -> None:
    state.input_tokens += usage.input_tokens
    state.output_tokens += usage.output_tokens
    state.cost_usd += usage.cost_usd


def run_pipeline(
    spec: BookSpec,
    *,
    provider: LLMProvider,
    out_path: str | Path,
    run_id: str | None = None,
    resume: bool = False,
    base_dir: str | Path = "runs",
    reporter: Reporter | None = None,
    config: Config | None = None,
    gather_sources: bool = True,
    render_pdf: bool = True,
) -> RunState:
    """Generate a book end-to-end (through verified resources), checkpointing as it goes.

    The roadmap and PDF rendering are layered on in later stages; this returns the
    run with all chapters drafted and (optionally) their resources attached.
    """
    reporter = reporter or Reporter()
    config = config or load_config()
    run_id = run_id or new_run_id(spec.topic)
    store = RunStore(run_id, base_dir)
    store.ensure()

    if resume and store.state_path.exists():
        state = store.load_state()
        reporter.info(f"Resuming run '{run_id}' at stage '{state.stage}'.")
    else:
        state = RunState(run_id=run_id, spec=spec, out_path=str(out_path))
        store.save_state(state)

    # Stage 1 — outline (skipped if already present from a prior run).
    if state.outline is None:
        reporter.stage("outline", "planning the table of contents")
        outline, usage = build_outline(provider, spec)
        state.outline = outline
        _add_usage(state, usage)
        state.stage = "outline"
        store.save_state(state)

    assert state.outline is not None
    chapters = state.outline.chapters
    total = len(chapters)

    # Stage 2 — draft chapters sequentially, skipping completed ones.
    reporter.stage("drafting", f"{total} chapters")
    for index, chapter in enumerate(chapters, start=1):
        if chapter.id in state.completed_chapter_ids and store.chapter_path(chapter.id).exists():
            reporter.info(f"Chapter {index}/{total} '{chapter.title}' already done — skipping.")
            continue

        reporter.chapter_start(index, total, chapter.title)
        recap, already_introduced = build_recap(chapters[: index - 1])
        draft, usage = draft_chapter(
            provider, spec, state.outline, chapter, recap, already_introduced,
            on_delta=reporter.chapter_delta, on_warn=reporter.warn,
        )
        store.save_chapter(draft)
        if chapter.id not in state.completed_chapter_ids:
            state.completed_chapter_ids.append(chapter.id)
        _add_usage(state, usage)
        state.stage = "drafting"
        store.save_state(state)
        reporter.chapter_done(index, total, chapter.title, usage)

    state.stage = "drafted"
    store.save_state(state)

    # Stage 3 — gather & verify resources per chapter (idempotent: a chapter that
    # already has resources is skipped, so this resumes cleanly too).
    if gather_sources:
        from ..resources import default_providers, default_validator, gather_resources

        providers = default_providers(config)
        validator = default_validator(config)
        reporter.stage("resources", "gathering & verifying links")
        for index, chapter in enumerate(chapters, start=1):
            draft = store.load_chapter(chapter.id)
            if draft.resources:
                continue
            try:
                resources, usage = gather_resources(
                    provider, spec, chapter,
                    providers=providers, validator=validator,
                    max_results=config.max_resources_per_chapter,
                )
                draft.resources = resources
                _add_usage(state, usage)
                store.save_chapter(draft)
                store.save_state(state)  # persist usage totals per chapter
                reporter.info(f"  {chapter.title}: {len(resources)} resources")
            except Exception as exc:  # resilient — a flaky search never kills the run
                reporter.warn(f"  resource gathering failed for '{chapter.title}': {exc}")
        state.stage = "resourced"
        store.save_state(state)

    # Stage 4 — assemble themed HTML and render the PDF.
    if render_pdf:
        from ..render import build_html, get_renderer

        reporter.stage("render", "assembling & rendering the PDF")
        drafts = [store.load_chapter(c.id) for c in chapters]
        html = build_html(spec, state.outline, drafts, learner_name=spec.profile.name)
        store.html_path.write_text(html, encoding="utf-8")
        get_renderer().render(html, out_path)
        state.out_path = str(out_path)
        state.stage = "done"
        store.save_state(state)
        reporter.info(f"PDF written to {out_path}")

        # Post-render quality check (best-effort; never fails the run).
        try:
            from ..render import analyze_pdf

            report = analyze_pdf(out_path)
            if report.ok:
                reporter.info(f"Quality check: {report.page_count} pages, no layout issues.")
            else:
                for issue in report.issues:
                    reporter.warn(f"Quality: {issue}")
        except Exception as exc:
            reporter.warn(f"Quality check skipped: {exc}")

    return state
