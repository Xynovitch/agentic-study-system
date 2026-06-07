"""Phase 1 — Knowledge Synthesis (Ingestion Engine).

Parses a week's bilingual PDFs and synthesizes three tiered Markdown files
(Beginner / Intermediate / Advanced), each enforcing the pedagogical rules via
the shared validate-and-retry loop.

These decks are mostly *images of text*, so `core.pdf_parser` OCRs (Tesseract,
kor+eng) any page whose embedded text layer is sparse — without that, the
text-only gpt-oss backend would be blind to them. Each source deck is synthesized
**separately** and the per-source sections are concatenated into one tier file, so
a week holding two different topics (e.g. Programming Languages + Computer
Networks) never drops one of them.
"""
from __future__ import annotations

from pathlib import Path

from core.base_agent import BaseAgent
from core.config import Settings
from core.llm_router import LLMRouter
from core.pdf_parser import ParsedPDF, parse_week_inputs
from core.validators import SYNTHESIS_RULES

# Tier -> the altitude guidance injected into the system prompt (from prompt.md).
TIERS: dict[str, str] = {
    "Beginner": (
        "Broad conceptual strokes. Cover what the concept is, the family of related ideas, "
        "the basic methods, and why it matters to computers. Example for 'binary': the idea of "
        "a base counting system, different counting systems, how you calculate in them, and why "
        "computers care."
    ),
    "Intermediate": (
        "Process and application. Cover the specific reasons behind the concept, the exact "
        "step-by-step procedure, and how it is applied/encoded. Example for 'binary': WHY binary "
        "is used, the step-by-step calculation process, and how encoding works."
    ),
    "Advanced": (
        "The nitty-gritty. Cover hardware-level mechanics and deeper theory. Example for "
        "'binary': hardware-level calculation (logic gates, adders) and theoretical tangents like "
        "ternary (삼진법) systems."
    ),
}


class IngestionAgent(BaseAgent):
    def __init__(self, settings: Settings, router: LLMRouter):
        super().__init__(
            "ingestion", settings, router, system_prompt_file="ingestion.md"
        )
        extras = self.route.extras
        self.ocr = bool(extras.get("ocr", True))
        self.ocr_langs = str(extras.get("ocr_langs", "kor+eng"))
        self.ocr_min_chars = int(extras.get("ocr_min_chars", 40))
        self.max_tokens = int(extras.get("max_tokens", 12000))

    def ingest_week(self, week_dir: Path, week: int) -> dict[str, Path]:
        """Parse PDFs and synthesize the three tier files. Returns {tier: path}."""
        parsed = parse_week_inputs(
            week_dir / "input", week_dir / "assets",
            ocr=self.ocr, ocr_langs=self.ocr_langs, ocr_min_chars=self.ocr_min_chars,
        )
        if not parsed:
            raise FileNotFoundError(
                f"No PDFs in {week_dir / 'input'}. Drop the weekly slides there first."
            )

        outputs: dict[str, Path] = {}
        for tier, guidance in TIERS.items():
            system = (
                self.system_prompt
                .replace("{{TIER}}", tier)
                .replace("{{TIER_GUIDANCE}}", guidance)
            )
            sections = [
                self._synthesize_source(system, tier, week, p)
                for p in parsed
                if p.full_text.strip()
            ]
            out_path = week_dir / f"{tier}.md"
            out_path.write_text(self._assemble(tier, week, sections), encoding="utf-8")
            outputs[tier] = out_path
        return outputs

    # ----------------------------------------------------------------- helpers
    def _synthesize_source(
        self, system: str, tier: str, week: int, parsed: ParsedPDF
    ) -> str:
        """Synthesize one tier's notes for a SINGLE source deck."""
        user = {
            "role": "user",
            "content": (
                f"Below is the extracted/OCR'd text of ONE lecture deck "
                f"('{parsed.source.name}') from Week {week}. The text comes from OCR of "
                f"bilingual slides, so it may contain artifacts or odd line breaks — interpret it "
                f"sensibly and correct obvious OCR errors. Synthesize the **{tier}** tier notes for "
                f"THIS deck, covering EVERY distinct topic it contains. Do not omit sections.\n\n"
                f"--- SLIDE TEXT ({parsed.source.name}) ---\n{parsed.full_text}\n--- END SLIDE TEXT ---"
            ),
        }
        return self.run_validated(
            [user], SYNTHESIS_RULES, system=system, max_tokens=self.max_tokens
        ).strip()

    @staticmethod
    def _assemble(tier: str, week: int, sections: list[str]) -> str:
        """Join per-source sections into one tier file (one section per deck)."""
        if not sections:
            return (
                f"# {tier} — Week {week:02d}\n\n"
                "_No readable text could be extracted from the slides, even via OCR. "
                "Re-scan the PDFs or provide a text-based deck, then re-ingest._\n"
            )
        return "\n\n---\n\n".join(sections) + "\n"
