"""Deterministic pedagogical rule checks.

LLMs are non-deterministic, so the five pedagogical rules from prompt.md cannot
rely on the model "remembering" them. Each rule is encoded here as a pure
function returning `(ok, message)`. `BaseAgent.run_validated` feeds the failure
message back to the model and re-prompts, bounding non-determinism with code.

Convention: a validator returns (True, "") on success, or (False, reason) where
`reason` is phrased as a concrete instruction the model can act on.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Callable, Sequence

# A validator maps generated text -> (passed, fix_instruction).
Validator = Callable[[str], tuple[bool, str]]

_HANGUL = re.compile(r"[가-힣]")  # Korean syllable block


@dataclass
class ValidationResult:
    ok: bool
    failures: list[str]


def run_validators(text: str, validators: Sequence[Validator]) -> ValidationResult:
    failures = [msg for v in validators for ok, msg in [v(text)] if not ok]
    return ValidationResult(ok=not failures, failures=failures)


def _strip_code_blocks(text: str) -> str:
    """Remove fenced code/mermaid blocks so prose rules ignore code identifiers."""
    return re.sub(r"```.*?```", "", text, flags=re.DOTALL)


# --------------------------------------------------------------------------- #
# Rule: Bilingual Integrity                                                     #
# Korean technical terms must sit in parentheses right after the English term.  #
# We flag Hangul that is NOT inside parentheses.                                #
# --------------------------------------------------------------------------- #
def korean_in_parentheses(text: str) -> tuple[bool, str]:
    prose = _strip_code_blocks(text)
    # Remove every parenthetical group; any Hangul left is "naked".
    naked = re.sub(r"\([^()]*\)", "", prose)
    stray = _HANGUL.findall(naked)
    if stray:
        sample = "".join(stray[:8])
        return False, (
            "Bilingual Integrity violation: Korean text must appear ONLY inside "
            f"parentheses immediately after the English term, e.g. 'binary (이진법)'. "
            f"Found Korean outside parentheses: '{sample}…'. Rewrite accordingly."
        )
    return True, ""


# --------------------------------------------------------------------------- #
# Rule: Dual Coding — a Mermaid.js diagram must be present.                     #
# --------------------------------------------------------------------------- #
def has_mermaid_block(text: str) -> tuple[bool, str]:
    if re.search(r"```mermaid\b", text):
        return True, ""
    return False, (
        "Dual Coding violation: include at least one Mermaid.js diagram in a "
        "```mermaid code block to visualize the concept."
    )


# --------------------------------------------------------------------------- #
# Rule: Metacognitive Scaffolding — no binary 'Correct/Incorrect' grading.     #
# Agents must trace where the mental model broke, not stamp a verdict.          #
# --------------------------------------------------------------------------- #
_GRADING = re.compile(
    r"(?<![\w])"
    r"(correct|incorrect|wrong|right answer|that'?s correct|well done|"
    r"good job|✓|✗|❌|✔️?)"
    r"(?![\w])",
    re.IGNORECASE,
)


def no_binary_grading(text: str) -> tuple[bool, str]:
    hits = {m.group(0).lower() for m in _GRADING.finditer(_strip_code_blocks(text))}
    if hits:
        return False, (
            "Metacognitive Scaffolding violation: do NOT issue verdicts like "
            f"{sorted(hits)}. Instead trace the logic step-by-step and pinpoint "
            "exactly where the reasoning broke down."
        )
    return True, ""


# --------------------------------------------------------------------------- #
# Rule: Worked-Example Effect — a solved example must precede abstract rules.   #
# --------------------------------------------------------------------------- #
_EXAMPLE_HDR = re.compile(r"^#+.*worked example", re.IGNORECASE | re.MULTILINE)
_RULES_HDR = re.compile(
    r"^#+.*(abstract rule|general rule|the rule|definition|formal|theory)",
    re.IGNORECASE | re.MULTILINE,
)


def worked_example_before_rules(text: str) -> tuple[bool, str]:
    ex = _EXAMPLE_HDR.search(text)
    if not ex:
        return False, (
            "Worked-Example violation: add a '## Worked Example' section with a "
            "fully solved step-by-step problem BEFORE any abstract rules."
        )
    rule = _RULES_HDR.search(text)
    if rule and rule.start() < ex.start():
        return False, (
            "Worked-Example violation: the worked example must come BEFORE the "
            "abstract rule/definition section. Reorder so the solved problem leads."
        )
    return True, ""


# --------------------------------------------------------------------------- #
# Rule: Interleaving — 20% of every quiz must revisit prior weeks.             #
# Only enforced when prior weeks exist; we check for the labelled section.      #
# --------------------------------------------------------------------------- #
_INTERLEAVE_HDR = re.compile(r"^#+.*interleav", re.IGNORECASE | re.MULTILINE)


def require_interleaving(enabled: bool) -> Validator:
    """Return a validator that demands an Interleaved Review section when enabled."""
    def _check(text: str) -> tuple[bool, str]:
        if not enabled or _INTERLEAVE_HDR.search(text):
            return True, ""
        return False, (
            "Interleaving violation: include an '## Interleaved Review' section drawing "
            "~20% of the questions from PRIOR weeks' material, to force long-term retention."
        )
    return _check


# --------------------------------------------------------------------------- #
# Rule: structured quiz — the Assessment Engine must emit a parseable JSON       #
# question bank (with answer keys) that meets the requested per-tier counts.     #
# --------------------------------------------------------------------------- #
QUIZ_TYPES = {"mcq", "cloze", "short", "essay"}
# Map the JSON tier label -> the config.yaml count key.
_TIER_TO_COUNT = {
    "Beginner": "beginner",
    "Intermediate": "intermediate",
    "Interleaved": "interleaved",
    "Advanced": "essays",
}


def parse_quiz_json(text: str) -> dict | None:
    """Extract the quiz JSON object, tolerating ```json fences or stray prose."""
    t = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", t, re.DOTALL)
    if fence:
        t = fence.group(1)
    else:
        start, end = t.find("{"), t.rfind("}")
        if start != -1 and end > start:
            t = t[start:end + 1]
    try:
        data = json.loads(t)
    except (json.JSONDecodeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def valid_quiz_json(expected: dict, interleave_enabled: bool) -> Validator:
    """Return a validator enforcing quiz JSON shape, answer keys, and tier counts.

    `expected` is the per-tier target counts (config.yaml: beginner/intermediate/
    interleaved/essays). Counts use a 60% floor so the model has slack but real
    shortfalls (e.g. the old "3 questions" bug) are still re-prompted.
    """
    def _check(text: str) -> tuple[bool, str]:
        data = parse_quiz_json(text)
        if data is None:
            return False, (
                'Quiz must be ONE valid JSON object {"week":..., "questions":[...]}. '
                "Output only JSON — no prose, no markdown, no code fences."
            )
        questions = data.get("questions")
        if not isinstance(questions, list) or not questions:
            return False, 'The JSON must contain a non-empty "questions" array.'

        for i, q in enumerate(questions):
            if not isinstance(q, dict):
                return False, f"questions[{i}] must be a JSON object."
            qtype = q.get("type")
            ident = q.get("id", i)
            if qtype not in QUIZ_TYPES:
                return False, (
                    f'questions[{i}].type must be one of {sorted(QUIZ_TYPES)}; got {qtype!r}.'
                )
            if not str(q.get("prompt", "")).strip():
                return False, f'Question {ident} is missing a non-empty "prompt".'
            if qtype == "mcq" and (not q.get("options") or not str(q.get("answer", "")).strip()):
                return False, f'mcq question {ident} needs "options" and a correct "answer" letter.'
            if qtype == "cloze" and not q.get("answers"):
                return False, f'cloze question {ident} needs a non-empty "answers" list.'
            if qtype == "short" and not str(q.get("answer", "")).strip():
                return False, f'short question {ident} needs a model "answer".'

        counts: dict[str, int] = {}
        for q in questions:
            counts[q.get("tier")] = counts.get(q.get("tier"), 0) + 1

        for tier, key in _TIER_TO_COUNT.items():
            if key == "interleaved" and not interleave_enabled:
                continue
            want = int(expected.get(key, 0) or 0)
            if want <= 0:
                continue
            floor = max(1, int(want * 0.6))
            got = counts.get(tier, 0)
            if got < floor:
                return False, (
                    f"Tier '{tier}' has only {got} question(s); generate about {want} "
                    f"(at least {floor}). The format is a template — these counts are the target."
                )

        if interleave_enabled and counts.get("Interleaved", 0) == 0:
            return False, (
                'Include Interleaved review questions ("tier":"Interleaved") drawn from prior '
                "weeks' material to force long-term retention; none were found."
            )
        return True, ""

    return _check


# Convenient bundles per agent.
SYNTHESIS_RULES: list[Validator] = [
    korean_in_parentheses,
    has_mermaid_block,
    worked_example_before_rules,
]
SOCRATIC_RULES: list[Validator] = [
    no_binary_grading,
    korean_in_parentheses,
]
FEYNMAN_RULES: list[Validator] = [
    no_binary_grading,
]
QUIZ_RULES: list[Validator] = [          # interleaving is appended per-call by the agent
    korean_in_parentheses,
]
GRADER_RULES: list[Validator] = [
    no_binary_grading,
    korean_in_parentheses,
]
