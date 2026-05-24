"""Phase 2 — Feedback / "check grading" engine.  [STUB]

Reviews quiz answers and reports current understanding, specific lacks, and
improvement paths. Like all agents here it obeys Metacognitive Scaffolding: it
traces where reasoning broke down rather than stamping Correct/Incorrect
(enforced by core.validators.no_binary_grading).
"""
from __future__ import annotations

from pathlib import Path

from core.base_agent import BaseAgent
from core.config import Settings
from core.llm_router import LLMRouter
from core.validators import no_binary_grading


class GraderAgent(BaseAgent):
    def __init__(self, settings: Settings, router: LLMRouter):
        super().__init__("grader", settings, router)

    def grade(self, quiz_path: Path, answers_path: Path, week: int) -> Path:
        """TODO(phase2): produce Feedback.md with understanding / lacks / next steps,
        validated against no_binary_grading."""
        raise NotImplementedError(
            "GraderAgent.grade is a Phase 2 TODO "
            f"(validator ready: {no_binary_grading.__name__})."
        )
