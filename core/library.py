"""Study library + inbox — the filesystem model behind the launcher.

A "study" is a Week folder under curriculum/. Loose PDFs are dropped into
study/inbox/ and later *assigned* to a week (which is when you choose to study
them). This module keeps that bookkeeping so the web layer stays thin.
"""
from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

TIER_FILES = ("Beginner.md", "Intermediate.md", "Advanced.md")
_WEEK_RE = re.compile(r"Week_(\d+)$")


@dataclass
class WeekInfo:
    week: int
    status: str                      # Empty | New | Ingested | Quizzed | Reviewed
    pdfs: list[str] = field(default_factory=list)
    tiers: list[str] = field(default_factory=list)
    has_quiz: bool = False
    has_answers: bool = False
    has_feedback: bool = False
    has_essay: bool = False
    has_critique: bool = False

    def to_dict(self) -> dict:
        return {
            "week": self.week,
            "status": self.status,
            "pdfs": self.pdfs,
            "tiers": self.tiers,
            "has_quiz": self.has_quiz,
            "has_answers": self.has_answers,
            "has_feedback": self.has_feedback,
            "has_essay": self.has_essay,
            "has_critique": self.has_critique,
        }


class Library:
    def __init__(self, root: Path):
        self.root = root
        self.curriculum = root / "curriculum"
        self.inbox = root / "study" / "inbox"
        self.curriculum.mkdir(parents=True, exist_ok=True)
        self.inbox.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------- inbox
    def list_inbox(self) -> list[str]:
        return sorted(p.name for p in self.inbox.glob("*.pdf"))

    def assign_inbox_to_week(self, filename: str, week: int) -> Path:
        """Move a dropped PDF into a week's input/ folder (creating the week)."""
        src = self.inbox / filename
        if not src.exists():
            raise FileNotFoundError(f"Inbox file not found: {filename}")
        dest_dir = self.create_week(week) / "input"
        dest = dest_dir / filename
        shutil.move(str(src), str(dest))
        return dest

    # ------------------------------------------------------------------- weeks
    def week_dir(self, week: int) -> Path:
        return self.curriculum / f"Week_{week:02d}"

    def create_week(self, week: int) -> Path:
        wdir = self.week_dir(week)
        (wdir / "input").mkdir(parents=True, exist_ok=True)
        (wdir / "assets").mkdir(parents=True, exist_ok=True)
        return wdir

    def next_week_number(self) -> int:
        existing = [w.week for w in self.list_weeks()]
        return (max(existing) + 1) if existing else 1

    def list_weeks(self) -> list[WeekInfo]:
        weeks = []
        for d in sorted(self.curriculum.glob("Week_*")):
            m = _WEEK_RE.search(d.name)
            if m:
                weeks.append(self.week_status(int(m.group(1))))
        return weeks

    def week_status(self, week: int) -> WeekInfo:
        wdir = self.week_dir(week)
        pdfs = sorted(p.name for p in (wdir / "input").glob("*.pdf")) \
            if (wdir / "input").exists() else []
        tiers = [t for t in TIER_FILES if (wdir / t).exists()]
        has_quiz = (wdir / "Quiz.md").exists()
        has_answers = (wdir / "Answers.md").exists()
        has_feedback = (wdir / "Feedback.md").exists()
        has_essay = (wdir / "Essay.md").exists()
        has_critique = (wdir / "Critique.md").exists()

        if has_critique:
            status = "Reviewed"
        elif has_quiz:
            status = "Quizzed"
        elif tiers:
            status = "Ingested"
        elif pdfs or has_essay:   # has source material to act on
            status = "New"
        else:
            status = "Empty"

        return WeekInfo(
            week=week, status=status, pdfs=pdfs, tiers=tiers,
            has_quiz=has_quiz, has_answers=has_answers, has_feedback=has_feedback,
            has_essay=has_essay, has_critique=has_critique,
        )
