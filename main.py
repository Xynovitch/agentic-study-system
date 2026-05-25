#!/usr/bin/env python3
"""Agentic Study System — CLI orchestrator.

Thin coordinator: it wires config -> router -> agents and passes *file paths*
between phases so its own context stays small. Phase 3 (Review) is fully
implemented; ingest/quiz are wired to working stubs.

Usage:
    python main.py serve   [--port 8000]             # Web launcher (browser UI)
    python main.py review  --week 1 [--essay PATH]   # Agent A: Socratic Dismantler
    python main.py feynman --week 1 [--model NAME]   # Agent B: Feynman Pupil
    python main.py ingest  --week 1                  # Phase 1: synthesize tiered notes
    python main.py quiz    --week 1                  # Phase 2: build quiz + answers template
    python main.py grade   --week 1                  # Phase 2: grade your answers
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from core.config import load_settings
from core.llm_router import LLMError, make_router
from core.state import Diagnostic


def week_dir(root: Path, week: int) -> Path:
    return root / "curriculum" / f"Week_{week:02d}"


def cmd_review(args, settings, router) -> int:
    from agents.socratic_dismantler import SocraticDismantler

    wdir = week_dir(settings.root, args.week)
    essay_path = Path(args.essay) if args.essay else wdir / "Essay.md"
    diagnostic = Diagnostic.open(settings.root / "state" / "Diagnostic.md")

    agent = SocraticDismantler(settings, router)
    print(f"⚔️  Socratic Dismantler reviewing {essay_path} "
          f"via {agent.engine}:{agent.model} …\n")
    result = agent.review(essay_path, args.week, diagnostic)

    print(result.critique_markdown)
    print("\n" + "=" * 60)
    print(f"✅ Critique written to {result.critique_path}")
    print(f"✅ {len(result.findings)} finding(s) appended to "
          f"{diagnostic.path}")
    return 0


def cmd_feynman(args, settings, router) -> int:
    from agents.feynman_pupil import FeynmanPupil

    diagnostic = Diagnostic.open(settings.root / "state" / "Diagnostic.md")
    agent = FeynmanPupil(settings, router)
    if args.model:  # per-invocation override (config stays per-agent default)
        object.__setattr__(agent.route, "model", args.model)
    agent.chat(diagnostic, args.week)
    return 0


def cmd_ingest(args, settings, router) -> int:
    from agents.ingestion_agent import IngestionAgent

    agent = IngestionAgent(settings, router)
    agent.ingest_week(week_dir(settings.root, args.week), args.week)
    return 0


def cmd_quiz(args, settings, router) -> int:
    from agents.quiz_agent import QuizAgent

    agent = QuizAgent(settings, router)
    prior = list(range(1, args.week))
    print(f"📝 Building Week {args.week} quiz via {agent.engine}:{agent.model} "
          f"(interleaving from weeks {prior or 'none'}) …")
    r = agent.build_quiz(week_dir(settings.root, args.week), args.week, prior)
    print(f"✅ Wrote {r.quiz_path}")
    print(f"✅ Wrote {r.answers_path}  ← fill this in, then run `grade`")
    if r.interleaved:
        print("   Included an Interleaved Review section (~20% prior weeks).")
    return 0


def cmd_grade(args, settings, router) -> int:
    from agents.grader_agent import GraderAgent

    wdir = week_dir(settings.root, args.week)
    diagnostic = Diagnostic.open(settings.root / "state" / "Diagnostic.md")
    agent = GraderAgent(settings, router)
    print(f"🧭 Grading Week {args.week} via {agent.engine}:{agent.model} …\n")
    result = agent.grade(wdir / "Quiz.md", wdir / "Answers.md", args.week, diagnostic)
    print(result.feedback_markdown)
    print("\n" + "=" * 60)
    print(f"✅ Feedback written to {result.feedback_path}")
    print(f"✅ {len(result.findings)} finding(s) appended to {diagnostic.path}")
    return 0


def cmd_serve(args, settings, router) -> int:
    import uvicorn

    print(f"🌐 Agentic Study launcher on http://127.0.0.1:{args.port}  (Ctrl-C to stop)")
    uvicorn.run("webapp.server:app", host="127.0.0.1", port=args.port, log_level="info")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="agentic-study", description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)

    def add_week(sp):
        sp.add_argument("--week", type=int, required=True, help="Week number, e.g. 1")

    r = sub.add_parser("review", help="Phase 3 Agent A: dismantle the Advanced essay")
    add_week(r)
    r.add_argument("--essay", help="Path to essay (default: curriculum/Week_NN/Essay.md)")
    r.set_defaults(func=cmd_review)

    f = sub.add_parser("feynman", help="Phase 3 Agent B: teach the curious novice")
    add_week(f)
    f.add_argument("--model", help="Override the Ollama model (e.g. qwen3:30b)")
    f.set_defaults(func=cmd_feynman)

    i = sub.add_parser("ingest", help="Phase 1: synthesize tiered notes (stub)")
    add_week(i)
    i.set_defaults(func=cmd_ingest)

    q = sub.add_parser("quiz", help="Phase 2: build a tiered quiz (+ Answers template)")
    add_week(q)
    q.set_defaults(func=cmd_quiz)

    g = sub.add_parser("grade", help="Phase 2: grade Answers.md (traced feedback)")
    add_week(g)
    g.set_defaults(func=cmd_grade)

    s = sub.add_parser("serve", help="Launch the browser study UI")
    s.add_argument("--port", type=int, default=8000, help="Port (default 8000)")
    s.set_defaults(func=cmd_serve)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = load_settings()
    router = make_router(settings)
    try:
        return args.func(args, settings, router)
    except LLMError as exc:
        print(f"\n🛑 LLM error: {exc}", file=sys.stderr)
        return 2
    except NotImplementedError as exc:
        print(f"\n🚧 {exc}", file=sys.stderr)
        return 3
    except (FileNotFoundError, ValueError) as exc:
        print(f"\n⚠️  {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
