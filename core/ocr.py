"""Local OCR for image-based lecture slides.

Korean/English ICS decks are largely *pictures of text* — the embedded PDF text
layer is near-empty (e.g. 412 chars across 38 pages). Under the text-only gpt-oss
backend the model is otherwise blind to them, so we OCR the rendered page images
locally with Tesseract (which ships `kor`+`eng` language data) and feed the
recovered text to ingestion.

The engine is hidden behind `ocr_image` so a higher-quality backend (Apple Vision
via `ocrmac`, etc.) can be swapped in later without touching callers.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path


class OCRUnavailable(RuntimeError):
    """Raised with an actionable fix hint when OCR cannot run."""


@lru_cache(maxsize=1)
def ocr_available() -> bool:
    """True if both the pytesseract wrapper and the tesseract binary are present."""
    try:
        import pytesseract
        pytesseract.get_tesseract_version()
        return True
    except Exception:  # noqa: BLE001 - any failure means OCR is unusable
        return False


def _require() -> None:
    if ocr_available():
        return
    try:
        import pytesseract  # noqa: F401
    except ModuleNotFoundError as exc:
        raise OCRUnavailable(
            "The 'pytesseract' package is not installed. Run: pip install -r requirements.txt"
        ) from exc
    raise OCRUnavailable(
        "The Tesseract OCR binary is not available on PATH. Install it with "
        "`brew install tesseract tesseract-lang` (the `kor` language data is required "
        "for the Korean slides), then retry."
    )


def ocr_image(png_path: Path | str, langs: str = "kor+eng") -> str:
    """Return the text Tesseract reads from one rendered page image.

    `langs` is a Tesseract spec like "kor+eng". Failures on a single page are
    swallowed (return "") so one bad page never aborts a whole ingest.
    """
    _require()
    import pytesseract

    try:
        return pytesseract.image_to_string(str(png_path), lang=langs).strip()
    except Exception:  # noqa: BLE001 - best-effort per page
        return ""
