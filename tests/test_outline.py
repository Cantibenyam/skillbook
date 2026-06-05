import pytest

from skillbook.generate.outline import _coerce_outline, build_outline, format_toc
from skillbook.llm import get_provider
from skillbook.models import DEPTH_PROFILES, BookSpec, Depth, Style
from skillbook.prompts import outline_system, style_directive


def test_build_outline_with_mock_assigns_ids_and_word_budgets():
    spec = BookSpec(topic="Learn Rust", depth=Depth.standard)
    outline, usage = build_outline(get_provider(mock=True), spec)
    assert outline.chapters, "expected chapters"
    assert [c.id for c in outline.chapters] == [f"ch{i:02d}" for i in range(1, len(outline.chapters) + 1)]
    expected_words = DEPTH_PROFILES[Depth.standard]["section_words"]
    assert all(s.target_words == expected_words for c in outline.chapters for s in c.sections)
    assert usage.output_tokens > 0


def test_coerce_fills_missing_sections_and_rejects_empty():
    spec = BookSpec(topic="X")
    out = _coerce_outline({"title": "T", "chapters": [{"title": "C1"}]}, spec)
    assert out.chapters[0].sections[0].title == "Overview"
    with pytest.raises(ValueError):
        _coerce_outline({"title": "T", "chapters": []}, spec)


def test_format_toc_is_readable():
    spec = BookSpec(topic="Learn Rust")
    outline, _ = build_outline(get_provider(mock=True), spec)
    toc = format_toc(outline)
    assert outline.title in toc
    assert "chapters ·" in toc
    assert "1." in toc


def test_outline_system_reflects_depth_and_style():
    prof = DEPTH_PROFILES[Depth.comprehensive]
    sys = outline_system(BookSpec(topic="X", depth=Depth.comprehensive, style=Style.scientific))
    assert str(prof["min_chapters"]) in sys and str(prof["max_chapters"]) in sys
    assert "academic register" in sys
    assert "casual register" in style_directive(Style.casual)
