"""Claude Code mode helpers — the deterministic, no-LLM toolkit.

In this mode the Claude Code agent is the author: it writes the outline and chapter
Markdown to a run directory, and uses these helpers for the parts that must be code:

* ``scaffold_run`` — create the run dir + a ``book.json`` skeleton.
* ``search_resources`` — provenance-first: return real, reachability-checked candidate
  links so the agent ranks/picks instead of inventing URLs.
* ``load_book`` / ``build_pdf`` — assemble the on-disk artifacts and render the PDF.

Run directory layout the agent fills in::

    <run>/book.json                      # meta: topic/title/subtitle/style/learner + chapter list
    <run>/chapters/<id>.md               # each chapter's Markdown
    <run>/chapters/<id>.resources.json   # (optional) chosen resources for that chapter
"""

from __future__ import annotations

import json
from pathlib import Path

from .config import Config
from .generate.pipeline import new_run_id
from .models import BookSpec, ChapterDraft, ChapterPlan, Outline, Profile, Resource, Style
from .render import build_html, get_renderer


def scaffold_run(
    topic: str,
    *,
    style: Style,
    runs_dir: str | Path = "runs",
    title: str = "",
    learner_name: str = "",
    out: str = "",
) -> Path:
    """Create ``<runs_dir>/<run_id>/`` with a ``book.json`` skeleton; return the dir."""
    run_id = new_run_id(topic)
    run_dir = Path(runs_dir) / run_id
    (run_dir / "chapters").mkdir(parents=True, exist_ok=True)
    meta = {
        "topic": topic,
        "title": title or topic,
        "subtitle": "",
        "style": style.value,
        "learner_name": learner_name,
        "out": out,
        "chapters": [],  # agent fills: [{"id": "ch01", "title": "..."}, ...]
    }
    (run_dir / "book.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return run_dir


def load_book(run_dir: Path) -> tuple[BookSpec, Outline, list[ChapterDraft]]:
    """Reconstruct (BookSpec, Outline, ChapterDrafts) from the agent's artifacts."""
    # utf-8-sig: tolerate a BOM (e.g. from editors / PowerShell-written files).
    meta = json.loads((run_dir / "book.json").read_text(encoding="utf-8-sig"))
    style = Style(meta.get("style", "casual"))
    learner = meta.get("learner_name", "")
    spec = BookSpec(
        topic=meta.get("topic") or meta.get("title") or "Untitled",
        style=style,
        profile=Profile(name=learner),
    )

    chapters_dir = run_dir / "chapters"
    plans: list[ChapterPlan] = []
    drafts: list[ChapterDraft] = []
    for i, ch in enumerate(meta.get("chapters") or [], start=1):
        cid = str(ch.get("id") or f"ch{i:02d}")
        title = str(ch.get("title") or f"Chapter {i}")
        plans.append(ChapterPlan(id=cid, title=title))

        md_file = chapters_dir / f"{cid}.md"
        markdown = md_file.read_text(encoding="utf-8-sig") if md_file.exists() else ""

        resources: list[Resource] = []
        res_file = chapters_dir / f"{cid}.resources.json"
        if res_file.exists():
            for r in json.loads(res_file.read_text(encoding="utf-8-sig")) or []:
                url = r.get("url")
                if not url:
                    continue
                resources.append(
                    Resource(
                        title=r.get("title") or url,
                        url=url,
                        source=r.get("source", "web"),
                        query=r.get("query", ""),
                        kind=r.get("kind", "article"),
                        snippet=r.get("snippet", ""),
                        status=r.get("status", "ok"),
                    )
                )
        drafts.append(ChapterDraft(id=cid, title=title, markdown=markdown, resources=resources))

    if not plans:
        raise ValueError(f"No chapters listed in {run_dir / 'book.json'}")

    outline = Outline(
        title=meta.get("title") or spec.topic,
        subtitle=meta.get("subtitle", ""),
        chapters=plans,
    )
    return spec, outline, drafts


def build_pdf(run_dir: Path, out_path: Path) -> Path:
    """Assemble the on-disk book and render it to ``out_path`` (no LLM)."""
    spec, outline, drafts = load_book(run_dir)
    html = build_html(spec, outline, drafts, learner_name=spec.profile.name)
    (run_dir / "book.html").write_text(html, encoding="utf-8")
    return get_renderer().render(html, out_path)


def search_resources(queries: list[str], *, providers, validator, limit: int = 5) -> list[dict]:
    """Run providers + reachability validation; return real candidates for the agent
    to rank. The agent must only use URLs that appear here (provenance-first)."""
    raw = []
    for query in queries:
        for provider in providers:
            for result in provider.search(query, limit=limit):
                result.query = query
                raw.append(result)
    validated = validator.validate(raw)
    return [
        {
            "url": r.final_url or r.url,
            "title": r.title,
            "snippet": r.snippet[:200],
            "source": r.source,
            "kind": r.kind,
            "status": r.status,
            "query": r.query,
        }
        for r in validated
    ]
