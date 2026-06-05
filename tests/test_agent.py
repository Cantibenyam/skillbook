import json

import pytest

from skillbook.agent_build import build_pdf, load_book, scaffold_run, search_resources
from skillbook.models import Style
from skillbook.resources.base import SearchResult


def _make_run(tmp_path, style="scientific"):
    run = tmp_path / "runs" / "demo"
    (run / "chapters").mkdir(parents=True)
    (run / "book.json").write_text(
        json.dumps(
            {
                "topic": "Learn SQL",
                "title": "Learn SQL",
                "subtitle": "A demo",
                "style": style,
                "learner_name": "Iman",
                "chapters": [{"id": "ch01", "title": "Basics"}, {"id": "ch02", "title": "Joins"}],
            }
        ),
        encoding="utf-8",
    )
    (run / "chapters" / "ch01.md").write_text(
        "Intro.\n\n## What is SQL\n\nText with `code`:\n\n```sql\nSELECT 1;\n```\n\n"
        "### Quiz\n\n1. Q?\n\n**Answers:** 1) A.\n",
        encoding="utf-8",
    )
    (run / "chapters" / "ch02.md").write_text("## Inner joins\n\nContent here.\n", encoding="utf-8")
    (run / "chapters" / "ch01.resources.json").write_text(
        json.dumps(
            [{"title": "PostgreSQL docs", "url": "https://www.postgresql.org/docs/", "source": "web", "query": "sql", "kind": "doc", "status": "ok"}]
        ),
        encoding="utf-8",
    )
    return run


def test_load_book_reads_artifacts(tmp_path):
    spec, outline, drafts = load_book(_make_run(tmp_path))
    assert spec.style is Style.scientific
    assert [c.id for c in outline.chapters] == ["ch01", "ch02"]
    assert "What is SQL" in drafts[0].markdown
    assert drafts[0].resources[0].url == "https://www.postgresql.org/docs/"
    assert drafts[1].resources == []


def test_build_pdf_from_agent_artifacts(tmp_path):
    run = _make_run(tmp_path, style="casual")
    out = tmp_path / "book.pdf"
    build_pdf(run, out)
    assert out.read_bytes()[:5] == b"%PDF-"
    assert (run / "book.html").exists()


def test_load_book_requires_chapters(tmp_path):
    run = tmp_path / "runs" / "empty"
    (run / "chapters").mkdir(parents=True)
    (run / "book.json").write_text(json.dumps({"topic": "X", "style": "casual", "chapters": []}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_book(run)


def test_scaffold_creates_skeleton(tmp_path):
    run = scaffold_run("Learn Rust", style=Style.casual, runs_dir=tmp_path / "runs")
    assert (run / "book.json").exists() and (run / "chapters").is_dir()
    meta = json.loads((run / "book.json").read_text(encoding="utf-8"))
    assert meta["topic"] == "Learn Rust" and meta["style"] == "casual"


class _FakeProvider:
    def __init__(self, name, urls):
        self.name = name
        self._urls = urls

    def search(self, query, *, limit=5):
        return [SearchResult(url=u, title=u, source=self.name) for u in self._urls]


class _FakeValidator:
    def validate(self, results, *, client=None):
        for r in results:
            r.status = "ok"
            r.final_url = r.url
        return results


def test_search_resources_formats_validated_candidates():
    prov = _FakeProvider("web", ["https://a.com", "https://b.com"])
    out = search_resources(["q1"], providers=[prov], validator=_FakeValidator(), limit=5)
    assert [r["url"] for r in out] == ["https://a.com", "https://b.com"]
    assert all(r["query"] == "q1" and r["source"] == "web" and r["status"] == "ok" for r in out)
