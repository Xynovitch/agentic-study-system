"""Phase 1 — Web Exploration sub-agent.  [STUB]

A context-isolating sub-agent: searches the web for real-world examples, photos,
and diagrams for a concept, then returns lightweight references (URL + caption +
source) so the ingestion agent can embed images and cite them. Kept separate so
the main orchestrator's context never holds raw search results.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class ImageRef:
    caption: str
    url: str
    source: str  # page the image came from, for attribution/licensing


class WebExplorer:
    def __init__(self, settings, router):
        self.settings = settings
        self.router = router

    def find_diagrams(self, concept: str, limit: int = 3) -> list[ImageRef]:
        """TODO(phase1): query a search API, filter for diagrams/photos, return refs."""
        raise NotImplementedError(
            "WebExplorer.find_diagrams is a Phase 1 TODO "
            f"(would search for: {concept!r})."
        )

    def download(self, ref: ImageRef, assets_dir: Path) -> Path:
        """TODO(phase1): fetch ref.url into assets_dir, returning the local path."""
        raise NotImplementedError("WebExplorer.download is a Phase 1 TODO.")
