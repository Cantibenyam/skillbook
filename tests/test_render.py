from skillbook.models import (
    BookSpec,
    ChapterDraft,
    ChapterPlan,
    Depth,
    Outline,
    Resource,
    Section,
    Style,
)
from skillbook.render import build_html, get_renderer


def _tiny_book(style=Style.casual):
    outline = Outline(
        title="Test Book",
        subtitle="A demo",
        chapters=[
            ChapterPlan(id="ch01", title="Getting Started", sections=[Section(title="Intro")]),
            ChapterPlan(id="ch02", title="Going Deeper", sections=[Section(title="More")]),
        ],
    )
    drafts = [
        ChapterDraft(
            id="ch01",
            title="Getting Started",
            markdown=(
                "Welcome.\n\n## Intro\n\nText with `code` and a block:\n\n"
                "```python\nprint('hi')\n```\n\n### Quiz\n\n1. Q?\n\n**Answers:** 1) A.\n"
            ),
            resources=[
                Resource(title="Python docs", url="https://docs.python.org/3/", source="web", query="python", kind="doc", status="ok"),
                Resource(title="Blocked one", url="https://ex.com/x", source="web", query="x", kind="article", status="unverified"),
            ],
        ),
        ChapterDraft(id="ch02", title="Going Deeper", markdown="## More\n\nDeeper content here."),
    ]
    return BookSpec(topic="Testing", style=style), outline, drafts


def test_build_html_structure_and_theme_swap():
    spec, outline, drafts = _tiny_book(Style.scientific)
    html = build_html(spec, outline, drafts, learner_name="Iman")
    assert "Test Book" in html
    assert 'class="mermaid"' in html and "flowchart TD" in html
    assert "chap-ch01" in html and "chap-ch02" in html
    assert "Further reading" in html and "Python docs" in html
    assert "unverified" in html
    assert "highlight" in html  # pygments highlighted the code block

    casual = build_html(_tiny_book(Style.casual)[0], outline, drafts)
    assert "#7c3aed" in casual  # casual violet accent
    assert "#7c3aed" not in html  # scientific uses a different accent
    assert "#0f766e" in html  # scientific teal accent
    assert "@font-face" in html  # vendored fonts inlined


def test_wrap_callouts_groups_exercise_and_quiz_sections():
    from skillbook.render.assemble import _wrap_callouts, md_to_html

    html = md_to_html(
        "Intro\n\n## Section\n\nText.\n\n### Worked example\n\n```py\nx=1\n```\n\n"
        "### Exercises\n\n1. Do X.\n\n### Quiz\n\n1. Q?\n\n**Answers:** A.\n"
    )
    wrapped = _wrap_callouts(html)
    assert "callout callout-example" in wrapped
    assert "callout callout-exercises" in wrapped
    assert "callout callout-quiz" in wrapped
    assert '<p class="callout-label">Exercises</p>' in wrapped
    assert ">Section<" in wrapped  # a normal section heading is left untouched


def test_render_resolves_mermaid_and_writes_valid_pdf(tmp_path):
    from playwright.sync_api import sync_playwright

    spec, outline, drafts = _tiny_book()
    html = build_html(spec, outline, drafts)

    # Verify Mermaid resolves from the vendored bundle and renders an SVG.
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content(html, wait_until="load", timeout=30000)
        page.wait_for_function("window.__mermaidDone === true", timeout=30000)
        error = page.evaluate("window.__mermaidError || null")
        svg_count = page.evaluate("document.querySelectorAll('.mermaid svg').length")
        browser.close()
    assert error is None, f"mermaid error: {error}"
    assert svg_count >= 1, "mermaid did not render an SVG"

    # Full render to PDF.
    out = tmp_path / "book.pdf"
    get_renderer().render(html, out)
    data = out.read_bytes()
    assert data[:5] == b"%PDF-"
    assert len(data) > 5000

    # The verifier reads it back: real pages, no blank pages.
    from skillbook.render.verify import analyze_pdf

    report = analyze_pdf(out)
    assert report.page_count >= 4  # cover + toc + roadmap + chapters
    assert report.blank_pages == []
    assert report.ok


def test_pipeline_end_to_end_offline_produces_pdf(tmp_path):
    """Full pipeline with the mock LLM (no network) renders a real PDF."""
    from skillbook.generate.pipeline import run_pipeline
    from skillbook.llm import get_provider

    spec = BookSpec(topic="Learn SQL", depth=Depth.primer)
    out = tmp_path / "books" / "sql.pdf"
    state = run_pipeline(
        spec,
        provider=get_provider(mock=True),
        out_path=out,
        base_dir=tmp_path / "runs",
        gather_sources=False,
        render_pdf=True,
    )
    assert state.stage == "done"
    assert out.exists() and out.read_bytes()[:5] == b"%PDF-"
    assert (tmp_path / "runs" / state.run_id / "book.html").exists()
