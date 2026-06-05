"""Rendering: assemble themed HTML and print it to PDF."""

from __future__ import annotations

from .assemble import build_html, md_to_html
from .base import PdfRenderer
from .playwright_renderer import PlaywrightRenderer
from .verify import QualityReport, analyze_pdf, rasterize_pages

__all__ = [
    "build_html",
    "md_to_html",
    "PdfRenderer",
    "PlaywrightRenderer",
    "get_renderer",
    "QualityReport",
    "analyze_pdf",
    "rasterize_pages",
]


def get_renderer() -> PdfRenderer:
    return PlaywrightRenderer()
