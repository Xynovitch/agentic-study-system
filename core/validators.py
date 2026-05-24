"""Deterministic pedagogical rule checks.

LLMs are non-deterministic, so the five pedagogical rules from prompt.md cannot
rely on the model "remembering" them. Each rule is encoded here as a pure
function returning `(ok, message)`. `BaseAgent.run_validated` feeds the failure
message back to the model and re-prompts, bounding non-determinism with code.

Convention: a validator returns (True, "") on success, or (False, reason) where
`reason` is phrased as a concrete instruction the model can act on.
"""
from __future__ import annotations

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
