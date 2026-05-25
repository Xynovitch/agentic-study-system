"""Phase 2 — Retention (Assessment Engine).

Generates a tiered quiz from the week's Phase 1 tier files, interleaving ~20% of
questions from prior weeks to force long-term retention. One API call produces
both the quiz and a matching blank answer template (split on `===ANSWERS===`).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from core.base_agent import BaseAgent
from core.config import Settings
from core.llm_router import LLMRouter
from core.validators import QUIZ_RULES, require_interleaving

TIER_FILES = ("Beginner.md", "Intermediate.md", "Advanced.md")
INTERLEAVE_RATIO = 0.20
_ANSWERS_DELIM = "===ANSWERS==="


@dataclass
class QuizResult:
    quiz_path: Path
    answers_path: Path
    interleaved: bool


class QuizAgent(BaseAgent):
    def __init__(self, settings: Settings, router: LLMRouter):
        super().__init__("quiz", settings, router, system_prompt_file="quiz.md")

    def build_quiz(self, week_dir: Path, week: int, prior_weeks: list[int]) -> QuizResult:
        """Generate Quiz.md + an Answers.md template. Returns the written paths."""
        tier_text = self._read_tiers(week_dir)
        if not tier_text:
            raise FileNotFoundError(
                f"No tier notes in {week_dir}. Run `ingest` for Week {week:02d} first."
            )
        prior_text = self._read_prior(week_dir.parent, prior_weeks)
        interleave = bool(prior_text)

        system = self.system_prompt.replace("{{WEEK}}", str(week))
        user = (
            f"Generate the Week {week} quiz from these tier notes.\n\n"
            f"=== THIS WEEK'S NOTES ===\n{tier_text}\n"
        )
        if interleave:
            pct = int(INTERLEAVE_RATIO * 100)
            user += (
                f"\n=== PRIOR WEEKS (draw ~{pct}% of questions from here) ===\n{prior_text}\n"
            )
        else:
            user += "\n(No prior weeks — omit the Interleaved Review section.)\n"

        validators = QUIZ_RULES + [require_interleaving(interleave)]
        raw = self.run_validated(
            [{"role": "user", "content": user}], validators, system=system, max_tokens=4096
        )

        quiz_md, answers_md = self._split(raw, week)
        quiz_path = week_dir / "Quiz.md"
        answers_path = week_dir / "Answers.md"
        quiz_path.write_text(quiz_md, encoding="utf-8")
        # Don't clobber answers the student already wrote.
        if not answers_path.exists():
            answers_path.write_text(answers_md, encoding="utf-8")

        return QuizResult(quiz_path=quiz_path, answers_path=answers_path, interleaved=interleave)

    # ----------------------------------------------------------------- helpers
    @staticmethod
    def _read_tiers(week_dir: Path) -> str:
        parts = []
        for name in TIER_FILES:
            p = week_dir / name
            if p.exists():
                parts.append(f"--- {name} ---\n{p.read_text(encoding='utf-8')}")
        return "\n\n".join(parts).strip()

    @staticmethod
    def _read_prior(curriculum: Path, prior_weeks: list[int]) -> str:
        """Condensed prior-week material (Beginner tier is enough for interleaving)."""
        parts = []
        for w in prior_weeks:
            wdir = curriculum / f"Week_{w:02d}"
            for name in ("Beginner.md", "Intermediate.md"):
                p = wdir / name
                if p.exists():
                    parts.append(f"--- Week {w:02d} / {name} ---\n{p.read_text(encoding='utf-8')}")
        return "\n\n".join(parts).strip()

    @staticmethod
    def _split(raw: str, week: int) -> tuple[str, str]:
        if _ANSWERS_DELIM in raw:
            quiz, _, answers = raw.partition(_ANSWERS_DELIM)
            return quiz.strip(), answers.strip() or QuizAgent._fallback_answers(week)
        return raw.strip(), QuizAgent._fallback_answers(week)

    @staticmethod
    def _fallback_answers(week: int) -> str:
        return (
            f"# Week {week} — My Answers\n\n"
            "_Write your answers below, numbered to match the quiz, then run grading._\n"
        )
