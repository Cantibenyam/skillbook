from skillbook.generate.chapters import build_recap, draft_chapter
from skillbook.generate.outline import build_outline
from skillbook.generate.pipeline import Reporter, RunStore, new_run_id, run_pipeline, slugify
from skillbook.llm import get_provider
from skillbook.llm.base import Completion, Usage
from skillbook.models import BookSpec, ChapterPlan, Depth, Outline, RunState, Section


class RecordingReporter(Reporter):
    def __init__(self) -> None:
        self.started: list[str] = []
        self.done: list[str] = []

    def chapter_start(self, index, total, title):
        self.started.append(title)

    def chapter_done(self, index, total, title, usage):
        self.done.append(title)


def test_save_state_is_atomic_and_leaves_no_tmp(tmp_path):
    store = RunStore("r", tmp_path)
    store.ensure()
    store.save_state(RunState(run_id="r", spec=BookSpec(topic="X")))
    assert store.state_path.exists()
    assert not list(store.dir.glob("*.tmp")), "atomic write must not leave a temp file"
    assert store.load_state().run_id == "r"


def test_slugify_and_run_id():
    assert slugify("Learn Rust!! (2026)") == "learn-rust-2026"
    assert slugify("") == "book"
    assert new_run_id("Learn Rust").startswith("learn-rust-")


def test_run_pipeline_drafts_all_chapters_and_checkpoints(tmp_path):
    spec = BookSpec(topic="Learn Rust", depth=Depth.primer)
    reporter = RecordingReporter()
    base = tmp_path / "runs"
    state = run_pipeline(
        spec, provider=get_provider(mock=True), out_path=tmp_path / "book.pdf",
        base_dir=base, reporter=reporter, gather_sources=False, render_pdf=False,
    )
    assert state.stage == "drafted"
    ids = [c.id for c in state.outline.chapters]
    assert state.completed_chapter_ids == ids
    assert len(reporter.started) == len(ids)

    store = RunStore(state.run_id, base)
    assert store.state_path.exists()
    for cid in ids:
        assert store.chapter_path(cid).exists()
        draft = store.load_chapter(cid)
        assert "### Quiz" in draft.markdown
    assert state.output_tokens > 0


def test_resume_is_idempotent_and_skips_completed(tmp_path):
    spec = BookSpec(topic="X", depth=Depth.primer)
    base = tmp_path / "runs"
    first = run_pipeline(spec, provider=get_provider(mock=True), out_path=tmp_path / "b.pdf", base_dir=base, gather_sources=False, render_pdf=False)

    reporter = RecordingReporter()
    again = run_pipeline(
        spec, provider=get_provider(mock=True), out_path=tmp_path / "b.pdf",
        run_id=first.run_id, resume=True, base_dir=base, reporter=reporter, gather_sources=False, render_pdf=False,
    )
    assert again.completed_chapter_ids == first.completed_chapter_ids
    assert reporter.started == [], "resume should not re-draft completed chapters"


def test_resume_regenerates_a_lost_chapter(tmp_path):
    spec = BookSpec(topic="X", depth=Depth.primer)
    base = tmp_path / "runs"
    state = run_pipeline(spec, provider=get_provider(mock=True), out_path=tmp_path / "b.pdf", base_dir=base, gather_sources=False, render_pdf=False)
    store = RunStore(state.run_id, base)

    # Simulate a crash that lost the final chapter.
    lost = state.outline.chapters[-1].id
    state.completed_chapter_ids.remove(lost)
    store.chapter_path(lost).unlink()
    state.stage = "drafting"
    store.save_state(state)

    reporter = RecordingReporter()
    resumed = run_pipeline(
        spec, provider=get_provider(mock=True), out_path=tmp_path / "b.pdf",
        run_id=state.run_id, resume=True, base_dir=base, reporter=reporter, gather_sources=False, render_pdf=False,
    )
    assert store.chapter_path(lost).exists()
    assert lost in resumed.completed_chapter_ids
    assert len(reporter.started) == 1  # only the lost chapter re-drafted


def test_build_recap_dedups_introduced_concepts():
    priors = [
        ChapterPlan(id="ch01", title="Basics", learning_objectives=["understand X"], introduces=["a", "b"]),
        ChapterPlan(id="ch02", title="More", learning_objectives=["do Y"], introduces=["b", "c"]),
    ]
    recap, introduced = build_recap(priors)
    assert "Basics" in recap and "More" in recap
    assert introduced == ["a", "b", "c"]
    assert build_recap([]) == ("", [])


class _TruncatingProvider:
    model = "mock/trunc"

    def __init__(self) -> None:
        self.calls = 0

    def stream_complete(self, system, messages, *, max_tokens, temperature=0.7, cacheable_system=False, on_delta=None):
        self.calls += 1
        if self.calls == 1:
            if on_delta:
                on_delta("PART1 ")
            return Completion(text="PART1 ", stop_reason="max_tokens", usage=Usage(10, 5, 0.0))
        if on_delta:
            on_delta("PART2")
        return Completion(text="PART2", stop_reason="stop", usage=Usage(8, 4, 0.0))


def test_draft_chapter_continues_after_truncation():
    chapter = ChapterPlan(id="ch01", title="T", sections=[Section(title="S", target_words=500)])
    outline = Outline(title="B", chapters=[chapter])
    prov = _TruncatingProvider()
    draft, usage = draft_chapter(prov, BookSpec(topic="X"), outline, chapter, "", [])
    assert draft.markdown == "PART1 PART2"
    assert prov.calls == 2
    assert usage.input_tokens == 18 and usage.output_tokens == 9
