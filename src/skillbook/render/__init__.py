"""Rendering: assemble themed HTML and print it to PDF."""

from __future__ import annotations

from .assemble import build_html, md_to_html
from .base import PdfRenderer
from .playwright_renderer import PlaywrightRenderer

__all__ = ["build_html", "md_to_html", "PdfRenderer", "PlaywrightRenderer", "get_renderer"]


def get_renderer() -> PdfRenderer:
    return PlaywrightRenderer()
