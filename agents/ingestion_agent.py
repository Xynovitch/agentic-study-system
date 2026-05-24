"""Phase 1 — Knowledge Synthesis (Ingestion Engine).

Parses a week's bilingual PDFs and synthesizes three tiered Markdown files
(Beginner / Intermediate / Advanced), each enforcing the pedagogical rules via
the shared validate-and-retry loop. Slide text AND a capped sample of rendered
page-images are sent to the vision-capable API model, because Korean slide text
often does not extract cleanly.
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
        self.max_images = int(self.route.extras.get("max_images", 10))

    def ingest_week(self, week_dir: Path, week: int) -> dict[str, Path]:
        """Parse PDFs and synthesize the three tier files. Returns {tier: path}."""
        parsed = parse_week_inputs(week_dir / "input", week_dir / "assets")
        if not parsed:
            raise FileNotFoundError(
                f"No PDFs in {week_dir / 'input'}. Drop the weekly slides there first."
            )

        slide_text = self._combine_text(parsed)
        images = self._sample_images(parsed)

        outputs: dict[str, Path] = {}
        for tier, guidance in TIERS.items():
            system = (
                self.system_prompt
                .replace("{{TIER}}", tier)
                .replace("{{TIER_GUIDANCE}}", guidance)
            )
            user = {
                "role": "user",
                "content": (
                    f"Here are this week's (Week {week}) lecture slides. The extracted text "
                    f"may be imperfect for Korean — use the attached page images to disambiguate. "
                    f"Synthesize the **{tier}** tier notes per your rules.\n\n"
                    f"--- SLIDE TEXT ---\n{slide_text}\n--- END SLIDE TEXT ---"
                ),
            }
            if images:
                user["images"] = images

            note = self.run_validated([user], SYNTHESIS_RULES, system=system, max_tokens=8192)
            out_path = week_dir / f"{tier}.md"
            out_path.write_text(note, encoding="utf-8")
            outputs[tier] = out_path
        return outputs

    # ----------------------------------------------------------------- helpers
    @staticmethod
    def _combine_text(parsed: list[ParsedPDF]) -> str:
        parts = []
        for p in parsed:
            parts.append(f"### Source: {p.source.name}\n{p.full_text}")
        return "\n\n".join(parts).strip() or "(no extractable text layer)"

    def _sample_images(self, parsed: list[ParsedPDF]) -> list[Path]:
        """Collect page images, evenly sampled down to self.max_images."""
        all_imgs: list[Path] = [img for p in parsed for img in p.image_paths]
        if len(all_imgs) <= self.max_images:
            return all_imgs
        step = len(all_imgs) / self.max_images
        return [all_imgs[int(i * step)] for i in range(self.max_images)]
