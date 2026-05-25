"""Study library + inbox — the filesystem model behind the launcher.

Layout is two levels: a **subject** (e.g. "Introduction to Computer Science")
is a folder under curriculum/ holding a `subject.json` and its own
`Diagnostic.md`; each subject contains **week** folders (`Week_NN/`). Loose PDFs
are dropped into the *shared* study/inbox/ and later *assigned* to a week of the
active subject. `Library` is scoped to one subject; `SubjectStore` manages the
set of subjects. This bookkeeping keeps the web layer thin.
"""
from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

TIER_FILES = ("Beginner.md", "Intermediate.md", "Advanced.md")
_WEEK_RE = re.compile(r"Week_(\d+)$")
_SLUG_STRIP = re.compile(r"[^a-z0-9]+")
DEFAULT_SUBJECT_NAME = "Introduction to Computer Science"


def slugify(name: str) -> str:
    """Filesystem-safe folder slug from a display name."""
    return _SLUG_STRIP.sub("-", name.strip().lower()).strip("-") or "subject"


@dataclass
class WeekInfo:
    week: int
    status: str                      # Empty | New | Ingested | Quizzed | Reviewed
    title: str = ""                  # optional display name; folder stays Week_NN
    pdfs: list[str] = field(default_factory=list)
    tiers: list[str] = field(default_factory=list)
    has_quiz: bool = False
    has_answers: bool = False
    has_feedback: bool = False
    has_essay: bool = False
    has_critique: bool = False
    has_diagrams: bool = False

    def to_dict(self) -> dict:
        return {
            "week": self.week,
            "status": self.status,
            "title": self.title,
            "pdfs": self.pdfs,
            "tiers": self.tiers,
            "has_quiz": self.has_quiz,
            "has_answers": self.has_answers,
            "has_feedback": self.has_feedback,
            "has_essay": self.has_essay,
            "has_critique": self.has_critique,
            "has_diagrams": self.has_diagrams,
        }


class Library:
    """Filesystem model scoped to one subject (or the curriculum root if none).

    Pass a subject *slug* to operate on that subject's weeks; the inbox is shared
    across subjects, so it always resolves to study/inbox/ regardless.
    """

    def __init__(self, root: Path, subject: str | None = None):
        self.root = root
        self.subject = subject
        self.curriculum_root = root / "curriculum"
        self.curriculum = self.curriculum_root / subject if subject else self.curriculum_root
        self.inbox = root / "study" / "inbox"
        self.curriculum.mkdir(parents=True, exist_ok=True)
        self.inbox.mkdir(parents=True, exist_ok=True)

    def diagnostic_path(self) -> Path:
        """This subject's Diagnostic.md (shared memory for the review agents)."""
        return self.curriculum / "Diagnostic.md"

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

    def assign_many(self, filenames: list[str], week: int) -> list[Path]:
        """Move several inbox PDFs into ONE week's input/ (the week is made once).

        This is what lets a week hold multiple PDFs: re-ingesting then folds them
        all into the tier notes. Missing files are reported before anything moves
        so a typo doesn't leave a half-assigned week.
        """
        missing = [f for f in filenames if not (self.inbox / f).exists()]
        if missing:
            raise FileNotFoundError(f"Inbox file(s) not found: {', '.join(missing)}")
        self.create_week(week)
        return [self.assign_inbox_to_week(f, week) for f in filenames]

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
        has_diagrams = (wdir / "Diagrams.md").exists()

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
            week=week, status=status, title=self.read_meta(week).get("title", ""),
            pdfs=pdfs, tiers=tiers,
            has_quiz=has_quiz, has_answers=has_answers, has_feedback=has_feedback,
            has_essay=has_essay, has_critique=has_critique, has_diagrams=has_diagrams,
        )

    # ----------------------------------------------------------- modify (Phase 3)
    def _meta_path(self, week: int) -> Path:
        return self.week_dir(week) / "meta.json"

    def read_meta(self, week: int) -> dict:
        p = self._meta_path(week)
        if not p.exists():
            return {}
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def set_title(self, week: int, title: str) -> str:
        """Set (or clear, if blank) a week's display title. Folder stays Week_NN."""
        self.create_week(week)
        meta = self.read_meta(week)
        title = title.strip()
        if title:
            meta["title"] = title
        else:
            meta.pop("title", None)
        self._meta_path(week).write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return title

    @staticmethod
    def _dedupe(dest_dir: Path, name: str) -> Path:
        """A non-colliding destination path: 'x.pdf' -> 'x (2).pdf' if taken."""
        dest = dest_dir / name
        if not dest.exists():
            return dest
        stem, suf = Path(name).stem, Path(name).suffix
        i = 2
        while (dest_dir / f"{stem} ({i}){suf}").exists():
            i += 1
        return dest_dir / f"{stem} ({i}){suf}"

    def move_pdf(self, filename: str, from_week: int, to: int | str) -> Path:
        """Move a PDF out of from_week/input into another week or back to inbox."""
        src = self.week_dir(from_week) / "input" / filename
        if not src.exists():
            raise FileNotFoundError(f"{filename} not found in Week {from_week:02d}.")
        if to == "inbox":
            dest_dir = self.inbox
        else:
            dest_dir = self.create_week(int(to)) / "input"
        dest = self._dedupe(dest_dir, filename)
        shutil.move(str(src), str(dest))
        return dest

    def delete_pdf(self, week: int, filename: str) -> None:
        p = self.week_dir(week) / "input" / filename
        if not p.exists():
            raise FileNotFoundError(f"{filename} not found in Week {week:02d}.")
        p.unlink()

    def delete_week(self, week: int) -> None:
        wdir = self.week_dir(week)
        if not wdir.exists():
            raise FileNotFoundError(f"Week {week:02d} not found.")
        shutil.rmtree(wdir)

    def merge_weeks(self, source: int, target: int) -> int:
        """Move all of source's PDFs into target, then delete source.

        Returns the number of PDFs moved. Derived files (notes/quiz/essay) of the
        source are discarded — re-ingest target to regenerate from the combined
        PDFs. Name collisions in target are de-duplicated, not overwritten.
        """
        if source == target:
            raise ValueError("Cannot merge a week into itself.")
        sdir = self.week_dir(source)
        if not sdir.exists():
            raise FileNotFoundError(f"Week {source:02d} not found.")
        if not self.week_dir(target).exists():
            raise FileNotFoundError(f"Week {target:02d} not found.")
        tgt_input = self.create_week(target) / "input"
        moved = 0
        src_input = sdir / "input"
        if src_input.exists():
            for pdf in sorted(src_input.glob("*.pdf")):
                shutil.move(str(pdf), str(self._dedupe(tgt_input, pdf.name)))
                moved += 1
        shutil.rmtree(sdir)
        return moved


# --------------------------------------------------------------------- subjects
@dataclass
class SubjectInfo:
    slug: str
    name: str
    weeks: int

    def to_dict(self) -> dict:
        return {"slug": self.slug, "name": self.name, "weeks": self.weeks}


class SubjectStore:
    """Manages subject folders under curriculum/.

    A subject is a directory containing a `subject.json` ({"name": ...}); its
    weeks live in `Week_NN/` subfolders. The folder name is a slug and never
    changes on rename (mirrors how weeks keep `Week_NN`), so paths stay stable.
    """

    def __init__(self, root: Path):
        self.root = root
        self.curriculum = root / "curriculum"
        self.curriculum.mkdir(parents=True, exist_ok=True)

    def _meta(self, slug: str) -> Path:
        return self.curriculum / slug / "subject.json"

    def subject_dir(self, slug: str) -> Path:
        return self.curriculum / slug

    def exists(self, slug: str) -> bool:
        return self._meta(slug).exists()

    def list_subjects(self) -> list[SubjectInfo]:
        out: list[SubjectInfo] = []
        for d in sorted(self.curriculum.iterdir()):
            meta = d / "subject.json"
            if not (d.is_dir() and meta.exists()):
                continue
            try:
                name = json.loads(meta.read_text(encoding="utf-8")).get("name", d.name)
            except (json.JSONDecodeError, OSError):
                name = d.name
            weeks = sum(1 for w in d.glob("Week_*") if w.is_dir())
            out.append(SubjectInfo(slug=d.name, name=name, weeks=weeks))
        return out

    def _unique_slug(self, name: str) -> str:
        base = slugify(name)
        slug, i = base, 2
        while (self.curriculum / slug).exists():
            slug, i = f"{base}-{i}", i + 1
        return slug

    def create_subject(self, name: str) -> str:
        name = name.strip()
        if not name:
            raise ValueError("Subject name cannot be empty.")
        slug = self._unique_slug(name)
        (self.curriculum / slug).mkdir(parents=True, exist_ok=True)
        self._meta(slug).write_text(
            json.dumps({"name": name}, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return slug

    def rename_subject(self, slug: str, name: str) -> str:
        name = name.strip()
        if not name:
            raise ValueError("Subject name cannot be empty.")
        if not self.exists(slug):
            raise FileNotFoundError(f"Subject not found: {slug}")
        self._meta(slug).write_text(
            json.dumps({"name": name}, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return name

    def delete_subject(self, slug: str) -> None:
        if not self.exists(slug):
            raise FileNotFoundError(f"Subject not found: {slug}")
        shutil.rmtree(self.curriculum / slug)


def ensure_migrated(root: Path, default_name: str = DEFAULT_SUBJECT_NAME) -> str | None:
    """Migrate a pre-subject layout into the subject layout, once.

    If week folders live flat under curriculum/ (old layout), create a default
    subject, move those weeks into it, and relocate the old global
    state/Diagnostic.md to the subject. Idempotent: a no-op once subjects exist
    and no flat weeks remain. Returns the created subject slug, or None.
    """
    curriculum = root / "curriculum"
    if not curriculum.exists():
        return None
    flat = [d for d in curriculum.glob("Week_*") if d.is_dir()]
    if not flat:
        return None
    store = SubjectStore(root)
    slug = store.create_subject(default_name)
    dest = curriculum / slug
    for wdir in flat:
        shutil.move(str(wdir), str(dest / wdir.name))
    old_diag = root / "state" / "Diagnostic.md"
    new_diag = dest / "Diagnostic.md"
    if old_diag.exists() and not new_diag.exists():
        shutil.move(str(old_diag), str(new_diag))
    return slug
