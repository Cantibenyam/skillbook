"""Assemble the book model into one self-contained themed HTML document.

The output inlines the theme CSS, Pygments code styles, and the vendored Mermaid
bundle, so the renderer can hand a single string to Chromium with no external
files or network. Switching ``casual`` ↔ ``scientific`` swaps only the theme CSS.
"""

from __future__ import annotations

import html as _html
from datetime import datetime
from importlib.resources import files

from markdown_it import MarkdownIt
from mdit_py_plugins.deflist import deflist_plugin
from mdit_py_plugins.footnote import footnote_plugin
from pygments import highlight as _pyg_highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name, guess_lexer

from ..generate.roadmap import build_roadmap_mermaid
from ..models import BookSpec, ChapterDraft, Outline, Resource


def _highlight(code: str, lang: str, attrs: str) -> str:
    try:
        lexer = get_lexer_by_name(lang) if lang else guess_lexer(code)
    except Exception:
        try:
            lexer = guess_lexer(code)
        except Exception:
            return f'<pre class="code"><code>{_html.escape(code)}</code></pre>'
    return _pyg_highlight(code, lexer, HtmlFormatter(nowrap=False))


# gfm-like gives tables + strikethrough. html=False escapes any raw HTML in the
# (LLM- or web-derived) content so it can't inject <script> into the page Chromium
# executes during rendering. linkify is disabled (no URLs in prose; avoids an extra dep).
_MD = (
    MarkdownIt("gfm-like", {"highlight": _highlight, "html": False, "linkify": False})
    .use(footnote_plugin)
    .use(deflist_plugin)
)


def md_to_html(text: str) -> str:
    return _MD.render(text or "")


def _read(pkg: str, name: str) -> str:
    return (files(pkg) / name).read_text(encoding="utf-8")


def _theme_css(style_value: str) -> str:
    base = _read("skillbook.render.themes", "base.css")
    theme = _read("skillbook.render.themes", f"{style_value}.css")
    return f"{base}\n{theme}"


def _chapter_anchor(chapter_id: str) -> str:
    return f"chap-{chapter_id}"


def _resources_html(resources: list[Resource]) -> str:
    if not resources:
        return ""
    items = []
    for r in resources:
        url = _html.escape(r.url, quote=True)
        title = _html.escape(r.title or r.url)
        kind = _html.escape(r.kind or "")
        src = _html.escape(r.source or "")
        badge = "" if r.status == "ok" else ' <span class="res-unverified">unverified</span>'
        items.append(
            f'<li><span class="res-kind">{kind}</span> '
            f'<a href="{url}">{title}</a> '
            f'<span class="res-src">{src}</span>{badge}</li>'
        )
    return (
        '<div class="resources"><h3>Further reading</h3>'
        f'<ul class="res-list">{"".join(items)}</ul></div>'
    )


def build_html(
    spec: BookSpec,
    outline: Outline,
    drafts: list[ChapterDraft],
    *,
    learner_name: str = "",
) -> str:
    by_id = {d.id: d for d in drafts}
    css = _theme_css(spec.style.value)
    pygments_css = HtmlFormatter().get_style_defs(".highlight")
    mermaid_src = build_roadmap_mermaid(outline)
    mermaid_js = _read("skillbook.render.assets", "mermaid.min.js")
    date = datetime.now().strftime("%B %Y")

    title = _html.escape(outline.title or spec.topic)
    subtitle = _html.escape(outline.subtitle or "")
    learner = _html.escape(learner_name or spec.profile.name or "")

    cover = [f'<section class="cover"><h1 class="book-title">{title}</h1>']
    if subtitle:
        cover.append(f'<p class="book-subtitle">{subtitle}</p>')
    meta = "A personalized SkillBook" + (f" for {learner}" if learner else "") + f" · {date}"
    cover.append(f'<p class="book-meta">{meta}</p></section>')

    toc = ['<nav class="toc"><h1>Contents</h1><ol>']
    for ch in outline.chapters:
        toc.append(f'<li><a href="#{_chapter_anchor(ch.id)}">{_html.escape(ch.title)}</a></li>')
    toc.append("</ol></nav>")

    roadmap = (
        '<section class="roadmap"><h1>Learning roadmap</h1>'
        f'<pre class="mermaid">{_html.escape(mermaid_src)}</pre></section>'
    )

    chapters = []
    for i, ch in enumerate(outline.chapters, start=1):
        draft = by_id.get(ch.id)
        body = md_to_html(draft.markdown if draft else "")
        resources = _resources_html(draft.resources if draft else [])
        chapters.append(
            f'<section class="chapter" id="{_chapter_anchor(ch.id)}">'
            f'<h1 class="chapter-title">{i}. {_html.escape(ch.title)}</h1>'
            f"{body}{resources}</section>"
        )

    # The vendored single-file bundle (esbuild IIFE) exposes Mermaid on a namespaced
    # global rather than window.mermaid, so resolve it defensively.
    init = (
        "(function(){"
        "var ns=window.__esbuild_esm_mermaid_nm;"
        "var m=window.mermaid||(ns&&ns.mermaid&&(ns.mermaid.default||ns.mermaid));"
        "if(!m){window.__mermaidDone=true;window.__mermaidError='mermaid not found';return;}"
        "m.initialize({startOnLoad:false,theme:'neutral',securityLevel:'strict',"
        "flowchart:{useMaxWidth:true,htmlLabels:true}});"
        "window.__mermaidDone=false;"
        "Promise.resolve(m.run()).then(function(){window.__mermaidDone=true;})"
        ".catch(function(e){window.__mermaidDone=true;window.__mermaidError=String(e);});"
        "})();"
    )

    return (
        "<!doctype html>\n"
        f'<html lang="en"><head><meta charset="utf-8"><title>{title}</title>\n'
        f"<style>{css}\n{pygments_css}</style></head>\n<body>\n"
        f'{"".join(cover)}\n{"".join(toc)}\n{roadmap}\n{"".join(chapters)}\n'
        f"<script>{mermaid_js}</script>\n<script>{init}</script>\n</body></html>"
    )
