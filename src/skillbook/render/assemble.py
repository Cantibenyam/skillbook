"""Assemble the book model into one self-contained, themed HTML document.

Inlines the vendored fonts (as data URIs), Pygments code styles, the theme CSS, and
the Mermaid bundle, so the renderer hands Chromium a single string with no external
files or network. Switching ``casual`` ↔ ``scientific`` swaps the theme palette + fonts
(and the prose register, set upstream); the structure is identical.
"""

from __future__ import annotations

import base64
import html as _html
import re
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

# Mermaid theme colors per register (the page palette lives in the CSS themes; these
# are the few values Mermaid needs as JS at render time).
_MERMAID = {
    "casual": {"accent": "#7c3aed", "soft": "#ede9fe", "ink": "#1f2430", "font": "Sora"},
    "scientific": {"accent": "#0f766e", "soft": "#cdfbf1", "ink": "#14213d", "font": "Source Serif 4"},
}

# Vendored fonts: (file, css family, weight, style).
_FONTS = [
    ("inter-400.woff2", "Inter", 400, "normal"),
    ("inter-600.woff2", "Inter", 600, "normal"),
    ("inter-700.woff2", "Inter", 700, "normal"),
    ("source-serif-400.woff2", "Source Serif 4", 400, "normal"),
    ("source-serif-600.woff2", "Source Serif 4", 600, "normal"),
    ("source-serif-400-italic.woff2", "Source Serif 4", 400, "italic"),
    ("sora-600.woff2", "Sora", 600, "normal"),
    ("sora-700.woff2", "Sora", 700, "normal"),
    ("jetbrains-mono-400.woff2", "JetBrains Mono", 400, "normal"),
    ("jetbrains-mono-600.woff2", "JetBrains Mono", 600, "normal"),
]

_font_css_cache: str | None = None


def _highlight(code: str, lang: str, attrs: str) -> str:
    try:
        lexer = get_lexer_by_name(lang) if lang else guess_lexer(code)
    except Exception:
        try:
            lexer = guess_lexer(code)
        except Exception:
            return f'<pre class="code"><code>{_html.escape(code)}</code></pre>'
    return _pyg_highlight(code, lexer, HtmlFormatter(nowrap=False))


_MD = (
    MarkdownIt("gfm-like", {"highlight": _highlight, "html": False, "linkify": False})
    .use(footnote_plugin)
    .use(deflist_plugin)
)


def md_to_html(text: str) -> str:
    return _MD.render(text or "")


def _read(pkg: str, name: str) -> str:
    return (files(pkg) / name).read_text(encoding="utf-8")


def _font_face_css() -> str:
    global _font_css_cache
    if _font_css_cache is None:
        fonts_dir = files("skillbook.render.assets") / "fonts"
        rules = []
        for fname, family, weight, style in _FONTS:
            data = (fonts_dir / fname).read_bytes()
            b64 = base64.b64encode(data).decode("ascii")
            rules.append(
                f"@font-face{{font-family:'{family}';font-style:{style};font-weight:{weight};"
                f"font-display:swap;src:url(data:font/woff2;base64,{b64}) format('woff2');}}"
            )
        _font_css_cache = "".join(rules)
    return _font_css_cache


def _pygments_css() -> str:
    for style in ("one-dark", "monokai", "default"):
        try:
            return HtmlFormatter(style=style).get_style_defs(".highlight")
        except Exception:
            continue
    return ""


def _theme_css(style_value: str) -> str:
    base = _read("skillbook.render.themes", "base.css")
    theme = _read("skillbook.render.themes", f"{style_value}.css")
    return f"{base}\n{theme}"


def _chapter_anchor(chapter_id: str) -> str:
    return f"chap-{chapter_id}"


# Wrap Exercises / Quiz / Worked-example sections (an <h3> + its body up to the next
# heading) into styled callout cards.
_HEADING_SPLIT = re.compile(r"(<h[1-6][^>]*>.*?</h[1-6]>)", re.IGNORECASE | re.DOTALL)
_CALLOUTS = {
    "worked example": ("example", "Worked example"),
    "example": ("example", "Example"),
    "exercises": ("exercises", "Exercises"),
    "exercise": ("exercises", "Exercises"),
    "practice": ("exercises", "Practice"),
    "quiz": ("quiz", "Quiz"),
    "self-check": ("quiz", "Self-check"),
}


def _callout_for(heading_inner: str) -> tuple[str, str] | None:
    text = re.sub(r"<[^>]+>", "", heading_inner).strip().lower()
    for key, value in _CALLOUTS.items():
        if text.startswith(key):
            return value
    return None


def _wrap_callouts(html: str) -> str:
    parts = _HEADING_SPLIT.split(html)
    out: list[str] = []
    i = 0
    while i < len(parts):
        seg = parts[i]
        match = re.match(r"<h3[^>]*>(.*?)</h3>\s*$", seg, re.IGNORECASE | re.DOTALL)
        callout = _callout_for(match.group(1)) if match else None
        if callout and i + 1 < len(parts):
            kind, label = callout
            body = parts[i + 1]
            out.append(
                f'<section class="callout callout-{kind}">'
                f'<p class="callout-label">{_html.escape(label)}</p>{body}</section>'
            )
            i += 2
        else:
            out.append(seg)
            i += 1
    return "".join(out)


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


def _mermaid_init(style_value: str) -> str:
    p = _MERMAID.get(style_value, _MERMAID["casual"])
    return (
        "(function(){"
        "var ns=window.__esbuild_esm_mermaid_nm;"
        "var m=window.mermaid||(ns&&ns.mermaid&&(ns.mermaid.default||ns.mermaid));"
        "if(!m){window.__mermaidDone=true;window.__mermaidError='mermaid not found';return;}"
        "m.initialize({startOnLoad:false,securityLevel:'strict',theme:'base',themeVariables:{"
        f"primaryColor:'{p['soft']}',primaryBorderColor:'{p['accent']}',primaryTextColor:'{p['ink']}',"
        f"lineColor:'{p['accent']}',fontFamily:'{p['font']}',fontSize:'15px'}},"
        "flowchart:{useMaxWidth:true,htmlLabels:true,curve:'basis',nodeSpacing:28,rankSpacing:34}});"
        "window.__mermaidDone=false;"
        # Wait for the inlined web fonts so Mermaid measures label widths correctly
        # (otherwise boxes are sized for a fallback font and the text clips).
        "var fr=(document.fonts&&document.fonts.ready)?document.fonts.ready:Promise.resolve();"
        "fr.then(function(){return Promise.resolve(m.run());})"
        ".then(function(){window.__mermaidDone=true;})"
        ".catch(function(e){window.__mermaidDone=true;window.__mermaidError=String(e);});"
        "})();"
    )


def build_html(
    spec: BookSpec,
    outline: Outline,
    drafts: list[ChapterDraft],
    *,
    learner_name: str = "",
) -> str:
    by_id = {d.id: d for d in drafts}
    style_value = spec.style.value
    css = f"{_font_face_css()}\n{_pygments_css()}\n{_theme_css(style_value)}"
    mermaid_src = build_roadmap_mermaid(outline)
    mermaid_js = _read("skillbook.render.assets", "mermaid.min.js")
    date = datetime.now().strftime("%B %Y")

    title = _html.escape(outline.title or spec.topic)
    subtitle = _html.escape(outline.subtitle or "")
    learner = _html.escape(learner_name or spec.profile.name or "")

    meta = "A personalized SkillBook" + (f" for {learner}" if learner else "") + f" · {date}"
    cover = (
        '<section class="cover"><div class="cover-band"></div>'
        '<p class="cover-kicker">SKILLBOOK</p>'
        f'<h1 class="book-title">{title}</h1>'
        + (f'<p class="book-subtitle">{subtitle}</p>' if subtitle else "")
        + f'<p class="book-meta">{meta}</p></section>'
    )

    toc = ['<nav class="toc"><h1>Contents</h1><ol>']
    for ch in outline.chapters:
        toc.append(f'<li><a href="#{_chapter_anchor(ch.id)}">{_html.escape(ch.title)}</a></li>')
    toc.append("</ol></nav>")

    roadmap = (
        '<section class="roadmap"><h1>Learning roadmap</h1>'
        f'<div class="roadmap-frame"><pre class="mermaid">{_html.escape(mermaid_src)}</pre></div></section>'
    )

    chapters = []
    for i, ch in enumerate(outline.chapters, start=1):
        draft = by_id.get(ch.id)
        body = _wrap_callouts(md_to_html(draft.markdown if draft else ""))
        resources = _resources_html(draft.resources if draft else [])
        chapters.append(
            f'<section class="chapter" id="{_chapter_anchor(ch.id)}">'
            f'<header class="chapter-head"><div class="chapter-num">{i:02d}</div>'
            f'<h1 class="chapter-title">{_html.escape(ch.title)}</h1></header>'
            f"{body}{resources}</section>"
        )

    return (
        "<!doctype html>\n"
        f'<html lang="en"><head><meta charset="utf-8"><title>{title}</title>\n'
        f"<style>{css}</style></head>\n<body>\n"
        f'{cover}\n{"".join(toc)}\n{roadmap}\n{"".join(chapters)}\n'
        f"<script>{mermaid_js}</script>\n<script>{_mermaid_init(style_value)}</script>\n</body></html>"
    )
