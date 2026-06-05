"""Post-render quality verifier.

Reads the finished PDF page by page (rasterized via pypdfium2 — permissive license,
no external binary) and flags layout problems the renderer can't see, chiefly
blank / near-empty pages (an accidental extra page).

The roadmap-splitting-across-pages problem is prevented at render time (the roadmap is
constrained to a single page via CSS ``max-height`` + ``break-inside: avoid``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# Ink-coverage thresholds (fraction of non-white pixels).
BLANK_INK = 0.0015  # < 0.15% inked -> effectively empty (a real defect on a body page)
SPARSE_INK = 0.02  # < 2% inked    -> low density (often a normal chapter end; informational)
FRONT_MATTER_PAGES = 3  # cover / contents / roadmap are allowed to be sparse


@dataclass
class PageStat:
    index: int  # 1-based page number
    ink: float  # fraction of inked pixels
    blank: bool
    sparse: bool


@dataclass
class QualityReport:
    pdf: str
    page_count: int = 0
    pages: list[PageStat] = field(default_factory=list)
    render_warnings: list[str] = field(default_factory=list)

    @property
    def blank_pages(self) -> list[int]:
        return [p.index for p in self.pages if p.blank]

    @property
    def sparse_pages(self) -> list[int]:
        return [p.index for p in self.pages if p.sparse and not p.blank]

    @property
    def issues(self) -> list[str]:
        """Real problems that make the book lower quality."""
        out = list(self.render_warnings)
        if self.blank_pages:
            out.append(f"blank / near-empty page(s): {self.blank_pages}")
        return out

    @property
    def notes(self) -> list[str]:
        """Informational observations (not necessarily defects)."""
        out: list[str] = []
        if self.sparse_pages:
            out.append(f"low-density page(s) (often normal chapter ends): {self.sparse_pages}")
        return out

    @property
    def ok(self) -> bool:
        return not self.issues


def analyze_pdf(
    pdf_path: str | Path, *, dpi: int = 70, render_warnings: list[str] | None = None
) -> QualityReport:
    """Rasterize each page and flag blank/sparse pages."""
    import pypdfium2 as pdfium

    path = Path(pdf_path)
    report = QualityReport(pdf=str(path), render_warnings=list(render_warnings or []))
    pdf = pdfium.PdfDocument(str(path))
    try:
        report.page_count = len(pdf)
        scale = dpi / 72.0
        for i in range(len(pdf)):
            image = pdf[i].render(scale=scale, grayscale=True).to_pil().convert("L")
            total = image.width * image.height
            inked = sum(image.histogram()[:240])  # pixels darker than ~"near white"
            frac = inked / total if total else 0.0
            # Front matter (cover/contents/roadmap) is allowed to be sparse; only flag
            # body pages, so a short-but-valid TOC isn't mistaken for an accidental blank.
            is_body = i >= FRONT_MATTER_PAGES
            blank = is_body and frac < BLANK_INK
            sparse = is_body and (not blank) and frac < SPARSE_INK
            report.pages.append(PageStat(index=i + 1, ink=round(frac, 4), blank=blank, sparse=sparse))
    finally:
        pdf.close()
    return report


def rasterize_pages(pdf_path: str | Path, out_dir: str | Path, *, dpi: int = 110) -> list[Path]:
    """Render each page to a PNG (for visual inspection); return the image paths."""
    import pypdfium2 as pdfium

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    pdf = pdfium.PdfDocument(str(pdf_path))
    paths: list[Path] = []
    try:
        scale = dpi / 72.0
        for i in range(len(pdf)):
            image = pdf[i].render(scale=scale).to_pil()
            page_png = out / f"page-{i + 1:02d}.png"
            image.save(page_png)
            paths.append(page_png)
    finally:
        pdf.close()
    return paths
