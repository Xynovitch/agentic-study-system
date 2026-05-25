"""Phase 1 — Web Exploration sub-agent.

A context-isolating sub-agent: searches **Wikimedia Commons** for real diagrams
and illustrations of a concept, downloads them into the week's `assets/`, and
writes a `Diagrams.md` that embeds them with caption + license + source link.
Commons is keyless, stable, and CC-licensed (so attribution is clean), unlike
scraping image search engines.

This is *best-effort enrichment*: every network path degrades to an empty result
rather than raising, because each tier note already carries a Mermaid diagram —
Dual Coding is satisfied with or without web images.
"""
from __future__ import annotations

import mimetypes
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import requests

from core.base_agent import BaseAgent
from core.config import Settings
from core.library import TIER_FILES, slugify
from core.llm_router import LLMRouter

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
_UA = "AgenticStudySystem/1.0 (local educational use; +https://github.com/)"
_IMG_EXTS = (".png", ".jpg", ".jpeg", ".svg", ".gif", ".webp")


@dataclass
class ImageRef:
    caption: str
    url: str          # direct (thumb) image URL to fetch
    source: str       # Commons description page, for attribution/licensing
    license: str = ""


class WebExplorer(BaseAgent):
    """Routes to the `api` engine only to turn notes into good search queries;
    the actual image lookup is a plain keyless HTTP call to Commons."""

    def __init__(self, settings: Settings, router: LLMRouter):
        super().__init__("web_explorer", settings, router)
        self.timeout = int(self.route.extras.get("timeout", 15))
        self.per_concept = int(self.route.extras.get("per_concept", 1))
        self.max_concepts = int(self.route.extras.get("max_concepts", 4))

    # --------------------------------------------------------------- search
    def find_diagrams(self, concept: str, limit: int = 3) -> list[ImageRef]:
        """Query Commons for a concept; return up to `limit` image refs ([] on error)."""
        params = {
            "action": "query", "format": "json", "generator": "search",
            "gsrnamespace": 6, "gsrsearch": concept, "gsrlimit": max(limit * 3, 6),
            "prop": "imageinfo", "iiprop": "url|extmetadata", "iiurlwidth": 1000,
        }
        try:
            resp = requests.get(COMMONS_API, params=params,
                                headers={"User-Agent": _UA}, timeout=self.timeout)
            resp.raise_for_status()
            pages = (resp.json().get("query") or {}).get("pages") or {}
        except (requests.RequestException, ValueError):
            return []

        refs: list[ImageRef] = []
        for pg in sorted(pages.values(), key=lambda p: p.get("index", 1 << 30)):
            ii = (pg.get("imageinfo") or [{}])[0]
            url = ii.get("thumburl") or ii.get("url") or ""
            if not url or not url.lower().split("?")[0].endswith(_IMG_EXTS):
                continue
            meta = ii.get("extmetadata") or {}
            title = pg.get("title", "")
            caption = title.removeprefix("File:").rsplit(".", 1)[0].replace("_", " ").strip()
            refs.append(ImageRef(
                caption=caption or concept,
                url=url,
                source=ii.get("descriptionurl", ""),
                license=(meta.get("LicenseShortName") or {}).get("value", ""),
            ))
            if len(refs) >= limit:
                break
        return refs

    def download(self, ref: ImageRef, assets_dir: Path) -> Path:
        """Fetch ref.url into assets_dir; return the local path. Raises on HTTP error."""
        assets_dir.mkdir(parents=True, exist_ok=True)
        resp = requests.get(ref.url, headers={"User-Agent": _UA}, timeout=self.timeout)
        resp.raise_for_status()
        name = (slugify(ref.caption) or "diagram")[:60] + self._ext_for(ref.url, resp.headers.get("Content-Type", ""))
        dest = self._dedupe(assets_dir, name)
        dest.write_bytes(resp.content)
        return dest

    # ----------------------------------------------------------- orchestration
    def enrich_week(self, week_dir: Path, week: int, concepts: list[str] | None = None) -> dict:
        """Find + download a diagram per concept and write Diagrams.md. Best-effort."""
        if concepts is None:
            concepts = self.concepts_from_notes(week_dir, week)
        assets_dir = week_dir / "assets"
        sections: list[str] = []
        for concept in concepts:
            for ref in self.find_diagrams(concept, limit=self.per_concept):
                try:
                    local = self.download(ref, assets_dir)
                except requests.RequestException:
                    continue
                attribution = (
                    f"[{ref.caption}]({ref.source})" if ref.source else ref.caption
                )
                if ref.license:
                    attribution += f" — {ref.license}"
                sections.append(
                    f"### {concept}\n\n"
                    f"![{ref.caption}](assets/{local.name})\n\n"
                    f"*Source: {attribution} (via Wikimedia Commons)*\n"
                )
        body = "# Reference Diagrams (참고 도해)\n\n"
        body += ("\n".join(sections) if sections else
                 "_No web diagrams found for this week's concepts — the tier notes' "
                 "Mermaid diagrams already cover Dual Coding._\n")
        out = week_dir / "Diagrams.md"
        out.write_text(body, encoding="utf-8")
        return {"path": out, "count": len(sections), "concepts": concepts}

    def concepts_from_notes(self, week_dir: Path, week: int) -> list[str]:
        """Pick diagram-worthy search queries from the week's notes.

        Uses the LLM when reachable; falls back to note headings (then a generic
        query) so the feature still works offline or without API credit.
        """
        notes = ""
        for tier in TIER_FILES:
            p = week_dir / tier
            if p.exists():
                notes += p.read_text(encoding="utf-8")[:2500] + "\n"
        if notes.strip():
            try:
                system = (
                    "You produce short English image-search queries for educational "
                    "diagrams. Output one query per line, no numbering or prose."
                )
                msg = [{
                    "role": "user",
                    "content": (
                        f"From these Week {week} notes, give up to {self.max_concepts} "
                        "concise queries for diagrams/illustrations that would aid "
                        f"understanding.\n\n{notes[:6000]}"
                    ),
                }]
                out = self.run(msg, system=system, max_tokens=200)
                queries = [ln.strip("-*0123456789. \t") for ln in out.splitlines()]
                queries = [q for q in queries if q]
                if queries:
                    return queries[: self.max_concepts]
            except Exception:  # noqa: BLE001 - any LLM/router issue -> fall back
                pass
        return self._heading_queries(week_dir) or [f"computer science week {week} diagram"]

    # ----------------------------------------------------------------- helpers
    @staticmethod
    def _heading_queries(week_dir: Path, limit: int = 4) -> list[str]:
        import re
        seen: list[str] = []
        paren = re.compile(r"\([^)]*\)")  # drop "(한국어)" parentheticals
        for tier in TIER_FILES:
            p = week_dir / tier
            if not p.exists():
                continue
            for line in p.read_text(encoding="utf-8").splitlines():
                if line.startswith("##"):
                    q = paren.sub("", line.lstrip("# ").strip()).strip()
                    if q and q.lower() not in (s.lower() for s in seen):
                        seen.append(q)
                if len(seen) >= limit:
                    return seen
        return seen

    @staticmethod
    def _ext_for(url: str, content_type: str) -> str:
        ext = os.path.splitext(urlparse(url).path)[1].lower()
        if ext in _IMG_EXTS:
            return ext
        guessed = mimetypes.guess_extension((content_type or "").split(";")[0].strip())
        return guessed or ".img"

    @staticmethod
    def _dedupe(dest_dir: Path, name: str) -> Path:
        dest = dest_dir / name
        if not dest.exists():
            return dest
        stem, suf = os.path.splitext(name)
        i = 2
        while (dest_dir / f"{stem}-{i}{suf}").exists():
            i += 1
        return dest_dir / f"{stem}-{i}{suf}"
