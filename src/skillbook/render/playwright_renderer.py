"""Render the assembled HTML to PDF with headless Chromium via Playwright.

Chromium runs the vendored Mermaid client-side; we wait for ``mermaid.run()`` to
finish (the documented async-render race) before printing, so diagrams aren't blank.
``outline=True`` emits PDF bookmarks from the heading structure; the in-document TOC
links remain clickable.
"""

from __future__ import annotations

from pathlib import Path


class PlaywrightRenderer:
    name = "playwright"

    def render(self, html: str, out_path: str | Path, *, timeout_ms: int = 30000) -> Path:
        from playwright.sync_api import Error as PWError
        from playwright.sync_api import TimeoutError as PWTimeout
        from playwright.sync_api import sync_playwright

        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        with sync_playwright() as p:
            try:
                browser = p.chromium.launch()
            except PWError as exc:
                raise RuntimeError(
                    "Could not launch Chromium for PDF rendering. "
                    "Run `playwright install chromium` once to download it."
                ) from exc
            try:
                page = browser.new_page()
                page.set_content(html, wait_until="load", timeout=timeout_ms)
                # Wait for Mermaid to finish (or fail) before printing.
                try:
                    page.wait_for_function("window.__mermaidDone === true", timeout=timeout_ms)
                except PWTimeout:
                    pass  # a stalled diagram must not block the whole PDF
                page.pdf(
                    path=str(out),
                    format="A4",
                    print_background=True,
                    prefer_css_page_size=True,
                    outline=True,
                    tagged=True,
                )
            finally:
                browser.close()
        return out
