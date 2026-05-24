"""Phase 2 — Retention (Assessment Engine).  [STUB]

Generates tiered quizzes from the Phase 1 tier files, with 20% interleaved
questions pulled from prior weeks to force long-term retention.
"""
from __future__ import annotations

from pathlib import Path

from core.base_agent import BaseAgent
from core.config import Settings
from core.llm_router import LLMRouter

TIER_FORMATS = {
    "Beginner": "multiple choice, cloze completion, and definitions",
    "Intermediate": "hands-on application and logic problems",
    "Advanced": "a comprehensive synthesis essay prompt",
}
INTERLEAVE_RATIO = 0.20  # 20% of items from prior weeks


class QuizAgent(BaseAgent):
    def __init__(self, settings: Settings, router: LLMRouter):
        super().__init__("quiz", settings, router)

    def build_quiz(self, week_dir: Path, week: int, prior_weeks: list[int]) -> Path:
        """TODO(phase2): read tier files, generate items, interleave ~20% prior weeks,
        write Quiz.md (and Essay.md prompt for the Advanced tier)."""
        raise NotImplementedError(
            "QuizAgent.build_quiz is a Phase 2 TODO "
            f"(interleave {int(INTERLEAVE_RATIO * 100)}% from weeks {prior_weeks})."
        )
