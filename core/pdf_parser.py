"""Bilingual PDF parsing for Phase 1 ingestion.

Korean/English lecture slides are image-heavy and CJK text extraction is often
garbled, so this module does two things per PDF: (1) pull whatever text layer
exists, and (2) render each page to a PNG so a vision-capable API model can read
slides directly. The ingestion agent then sends text + images together.

Uses pymupdf (imported as `fitz`), which is already installed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ParsedPDF:
    source: Path
    page_texts: list[str] = field(default_factory=list)
    image_paths: list[Path] = field(default_factory=list)

    @property
    def full_text(self) -> str:
        return "\n\n".join(
            f"[page {i + 1}]\n{t}" for i, t in enumerate(self.page_texts) if t.strip()
        )


def parse_pdf(pdf_path: Path, image_dir: Path, dpi: int = 150) -> ParsedPDF:
    """Extract per-page text and render per-page PNGs from one PDF."""
    try:
        import fitz  # pymupdf
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "pymupdf is not installed. Run: pip install -r requirements.txt"
        ) from exc

    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")
    image_dir.mkdir(parents=True, exist_ok=True)

    result = ParsedPDF(source=pdf_path)
    zoom = dpi / 72.0
    with fitz.open(pdf_path) as doc:
        matrix = fitz.Matrix(zoom, zoom)
        for i, page in enumerate(doc):
            result.page_texts.append(page.get_text("text"))
            out = image_dir / f"{pdf_path.stem}_p{i + 1:03d}.png"
            page.get_pixmap(matrix=matrix).save(out)
            result.image_paths.append(out)
    return result


def parse_week_inputs(input_dir: Path, image_dir: Path) -> list[ParsedPDF]:
    """Parse every PDF in a week's input/ folder (e.g. an EN and a KO deck)."""
    pdfs = sorted(input_dir.glob("*.pdf"))
    return [parse_pdf(p, image_dir) for p in pdfs]
