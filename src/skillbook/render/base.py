"""The PDF renderer contract.

A one-method seam so a different engine (e.g. a WeasyPrint 'print/academic' backend
for page-numbered TOCs) could be added later without touching callers — but only
Playwright/Chromium is implemented for the MVP.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class PdfRenderer(Protocol):
    name: str

    def render(self, html: str, out_path: str | Path, *, timeout_ms: int = 30000) -> Path: ...
