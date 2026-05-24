"""Agent A — The Socratic Dismantler (Phase 3, Review).

Ingests the week's Advanced Synthesis Essay and tears its reasoning apart:
attacks causal links, exposes logical leaps, demands edge cases. It NEVER grades
(Metacognitive Scaffolding rule, enforced by validators). Every flaw it finds is
appended to Diagnostic.md so the state file evolves week over week.

Context discipline: the orchestrator hands this agent a *path*, not essay text.
The essay is read here, kept local, and only a short summary is returned.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from core.base_agent import BaseAgent
from core.config import Settings
from core.llm_router import LLMRouter
from core.state import Diagnostic
from core.validators import SOCRATIC_RULES

# Matches the "Diagnostic Findings" bullets: "- [gap] ..." / "- [weakness] ..."
_FINDING = re.compile(r"^\s*[-*]\s*\[(gap|weakness)\]\s*(.+?)\s*$", re.IGNORECASE)


@dataclass
class CritiqueResult:
    critique_markdown: str
    critique_path: Path
    findings: list[str]


class SocraticDismantler(BaseAgent):
    def __init__(self, settings: Settings, router: LLMRouter):
        super().__init__(
            "socratic_dismantler",
            settings,
            router,
            system_prompt_file="socratic_dismantler.md",
        )

    def review(
        self,
        essay_path: Path,
        week: int,
        diagnostic: Diagnostic,
    ) -> CritiqueResult:
        if not essay_path.exists():
            raise FileNotFoundError(
                f"Essay not found: {essay_path}. Run Phase 1/2 first or pass --essay."
            )
        essay = essay_path.read_text(encoding="utf-8").strip()
        if not essay:
            raise ValueError(f"Essay is empty: {essay_path}")

        system = self.system_prompt.replace("{{WEEK}}", str(week))
        user = (
            f"Here is my Week {week} Advanced Synthesis Essay. Dismantle it per your "
            f"directives and output the required Markdown structure.\n\n"
            f"---\n{essay}\n---"
        )
        critique = self.run_validated(
            [{"role": "user", "content": user}],
            SOCRATIC_RULES,
            system=system,
        )

        critique_path = essay_path.parent / "Critique.md"
        critique_path.write_text(critique, encoding="utf-8")

        findings = self._extract_findings(critique)
        diagnostic.append_findings(week, "Socratic Dismantler", findings)

        return CritiqueResult(
            critique_markdown=critique,
            critique_path=critique_path,
            findings=findings,
        )

    @staticmethod
    def _extract_findings(critique: str) -> list[str]:
        """Pull the atomic findings bullets for logging into Diagnostic.md."""
        out: list[str] = []
        for line in critique.splitlines():
            m = _FINDING.match(line)
            if m:
                out.append(f"[{m.group(1).lower()}] {m.group(2)}")
        return out
