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


_END_COMMANDS = {"/done", "/quit", "/exit"}


class SocraticDismantler(BaseAgent):
    def __init__(self, settings: Settings, router: LLMRouter):
        super().__init__(
            "socratic_dismantler",
            settings,
            router,
            system_prompt_file="socratic_dismantler.md",
        )
        # Separate persona for the live debate turns (the one-shot critique prompt
        # above produces structured Markdown, which would be wrong per chat turn).
        self.debate_prompt = self._load_prompt("socratic_debate.md")

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

    # ------------------------------------------------------ live debate (chat)
    # Mirrors FeynmanPupil.start/respond/finish so the web WebSocket and any CLI
    # loop share one behaviour. The opening turn IS the written critique; from
    # there the student defends and Socrates rebuts the defense, one point at a
    # time, using the debate persona prompt.
    def open_debate(
        self, essay_path: Path, critique_path: Path, week: int
    ) -> tuple[list[dict], str]:
        """Open a debate: return (conversation, opening message = the critique)."""
        essay = essay_path.read_text(encoding="utf-8").strip()
        if not essay:
            raise ValueError(f"Essay is empty: {essay_path}")
        critique = critique_path.read_text(encoding="utf-8").strip()
        if not critique:
            raise ValueError(f"Critique is empty: {critique_path}. Run Review first.")

        setup = (
            f"This is the student's Week {week} Advanced Synthesis Essay, followed by your "
            f"written critique of it. The critique is your opening statement; the student will "
            f"now defend their reasoning against it and you will rebut their defenses.\n\n"
            f"=== STUDENT ESSAY ===\n{essay}\n\n=== YOUR CRITIQUE (opening statement) ===\n{critique}"
        )
        convo: list[dict] = [
            {"role": "user", "content": setup},
            {"role": "assistant", "content": critique},
        ]
        return convo, critique

    def respond(self, convo: list[dict], user_text: str) -> str:
        """Advance the debate one turn; mutates convo and returns Socrates' rebuttal."""
        convo.append({"role": "user", "content": user_text})
        reply = self.run_validated(convo, SOCRATIC_RULES, system=self.debate_prompt)
        convo.append({"role": "assistant", "content": reply})
        return reply

    def finish(self, convo: list[dict], week: int, diagnostic: Diagnostic) -> str:
        """End the debate: note unresolved weaknesses, append to Diagnostic.md."""
        summary = self._summarize_debate(convo, week)
        if summary:
            diagnostic.append_section(f"Socratic Debate — Week {week:02d}", summary)
        return summary

    def is_end_command(self, text: str) -> bool:
        return text.strip().lower() in _END_COMMANDS

    def _summarize_debate(self, convo: list[dict], week: int) -> str:
        transcript = "\n".join(
            f"{'Socrates' if m['role'] == 'assistant' else 'Student'}: {m['content']}"
            for m in convo[1:]  # skip the essay+critique setup turn
            if m["role"] in ("assistant", "user")
        )
        try:
            return self.run(
                [{"role": "user", "content": (
                    "Summarize this debate in 3-5 Markdown bullets: which weaknesses the student "
                    "defended successfully, which remain unresolved, and any new gaps the exchange "
                    "exposed. Be specific. Do NOT grade or praise.\n\n" + transcript
                )}],
                system="You write terse, factual study notes in Markdown bullets.",
                max_tokens=512,
            ).strip()
        except Exception as exc:  # noqa: BLE001 - summary is best-effort
            return f"_(summary unavailable: {exc})_"

    @staticmethod
    def _extract_findings(critique: str) -> list[str]:
        """Pull the atomic findings bullets for logging into Diagnostic.md."""
        out: list[str] = []
        for line in critique.splitlines():
            m = _FINDING.match(line)
            if m:
                out.append(f"[{m.group(1).lower()}] {m.group(2)}")
        return out
