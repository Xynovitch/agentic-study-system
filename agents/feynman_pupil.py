"""Agent B — The Feynman Pupil (Phase 3, Review).

Reads Diagnostic.md, then opens a terminal chat playing a curious but completely
uninitiated novice. It forces the student to teach concepts back, relentlessly
asking "Why?" and poking holes until the explanation is jargon-free. Runs on the
local Ollama "Fast Chatter" for low-latency back-and-forth.

I/O is injected (input_fn/output_fn) so the loop is unit-testable and scriptable.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

from core.base_agent import BaseAgent
from core.config import Settings
from core.llm_router import LLMRouter
from core.state import Diagnostic
from core.validators import FEYNMAN_RULES

InputFn = Callable[[str], str]
OutputFn = Callable[[str], None]

_END_COMMANDS = {"/done", "/quit", "/exit"}


class FeynmanPupil(BaseAgent):
    def __init__(self, settings: Settings, router: LLMRouter):
        super().__init__(
            "feynman_pupil",
            settings,
            router,
            system_prompt_file="feynman_pupil.md",
        )

    # ------------------------------------------------------------------ public
    # --------------------------------------------------- reusable turn methods
    # These are non-interactive so both the CLI loop and the web WebSocket
    # handler share the exact same behaviour.
    def start(self, diagnostic: Diagnostic, week: int) -> tuple[list[dict], str]:
        """Open a session: return (conversation, opening question)."""
        seed = self._seed_from_diagnostic(diagnostic)
        opening_prompt = (
            "Here are the student's known weaknesses and conceptual gaps:\n\n"
            f"{seed}\n\n"
            "Pick the single most important gap and ask your first innocent, "
            "jargon-free question to get the student teaching you. One question only."
        )
        convo: list[dict] = [{"role": "user", "content": opening_prompt}]
        reply = self.run_validated(convo, FEYNMAN_RULES)
        convo.append({"role": "assistant", "content": reply})
        return convo, reply

    def respond(self, convo: list[dict], user_text: str) -> str:
        """Advance one turn; mutates convo in place and returns the pupil reply."""
        convo.append({"role": "user", "content": user_text})
        reply = self.run_validated(convo, FEYNMAN_RULES)
        convo.append({"role": "assistant", "content": reply})
        return reply

    def finish(self, convo: list[dict], week: int, diagnostic: Diagnostic) -> str:
        """End the session: summarize and append to Diagnostic.md."""
        summary = self._summarize(convo, week)
        if summary:
            diagnostic.append_section(f"Feynman Session — Week {week:02d}", summary)
        return summary

    def is_end_command(self, text: str) -> bool:
        return text.strip().lower() in _END_COMMANDS

    # --------------------------------------------------------------- CLI loop
    def chat(
        self,
        diagnostic: Diagnostic,
        week: int,
        *,
        input_fn: InputFn = input,
        output_fn: OutputFn = print,
        max_turns: int = 100,
    ) -> str:
        """Run the interactive terminal Feynman loop. Returns the summary text."""
        output_fn(
            f"\n🧒 Feynman Pupil  ·  Week {week:02d}  ·  model: {self.model}\n"
            "Teach me until I get it. Type /done when you want to stop.\n"
            + "-" * 60
        )

        convo, reply = self.start(diagnostic, week)
        output_fn(f"\n🧒 Pupil: {reply}\n")

        turns = 0
        while turns < max_turns:
            try:
                user_text = input_fn("👩‍🏫 You: ").strip()
            except (EOFError, KeyboardInterrupt):
                output_fn("\n(ending session)")
                break
            if not user_text:
                continue
            if self.is_end_command(user_text):
                break
            output_fn(f"\n🧒 Pupil: {self.respond(convo, user_text)}\n")
            turns += 1

        summary = self.finish(convo, week, diagnostic)
        if summary:
            output_fn("\n📝 Session summary appended to Diagnostic.md.")
        return summary

    # ----------------------------------------------------------------- helpers
    @staticmethod
    def _seed_from_diagnostic(diagnostic: Diagnostic) -> str:
        """Extract Weaknesses + Conceptual Gaps + recent findings as seed topics."""
        text = diagnostic.read()
        wanted = ("Weaknesses", "Conceptual Gaps", "Findings Log")
        chunks: list[str] = []
        for section in re.split(r"^## ", text, flags=re.MULTILINE)[1:]:
            title = section.splitlines()[0].strip()
            if any(title.startswith(w) for w in wanted):
                body = section[len(title):].strip()
                if body and "_None recorded yet._" not in body:
                    chunks.append(f"{title}:\n{body}")
        return "\n\n".join(chunks) if chunks else (
            "No specific gaps logged yet — start by asking the student to explain "
            "this week's hardest concept in the simplest possible terms."
        )

    def _summarize(self, convo: list[dict], week: int) -> str:
        """Use the local model to note what the student struggled to simplify."""
        transcript = "\n".join(
            f"{'Pupil' if m['role'] == 'assistant' else 'Teacher'}: {m['content']}"
            for m in convo
            if m["role"] in ("assistant", "user")
        )
        try:
            return self.run(
                [
                    {
                        "role": "user",
                        "content": (
                            "Summarize this teaching session in 3-5 bullet points: which "
                            "concepts the teacher still explained with jargon or could not "
                            "reduce to simple terms, and which gaps remain. Be specific. "
                            "Do NOT grade or praise.\n\n" + transcript
                        ),
                    }
                ],
                system="You write terse, factual study notes in Markdown bullets.",
                max_tokens=512,
            ).strip()
        except Exception as exc:  # noqa: BLE001 - summary is best-effort
            return f"_(summary unavailable: {exc})_"
