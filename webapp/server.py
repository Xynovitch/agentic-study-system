"""FastAPI web server — the study launcher.

A thin HTTP/WebSocket layer over the existing agents and the Library. Long LLM
calls run in a worker thread (`asyncio.to_thread`) so the event loop — and the
live Feynman chat — stay responsive. Designed for local single-user use.

Run with:  python main.py serve   (or: uvicorn webapp.server:app)
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from core.config import load_settings
from core.library import Library
from core.llm_router import LLMError, make_router
from core.state import Diagnostic

settings = load_settings()
router = make_router(settings)
library = Library(settings.root)

STATIC_DIR = Path(__file__).resolve().parent / "static"
DIAGNOSTIC_PATH = settings.root / "state" / "Diagnostic.md"

app = FastAPI(title="Agentic Study System")


def diagnostic() -> Diagnostic:
    return Diagnostic.open(DIAGNOSTIC_PATH)


# --------------------------------------------------------------------- pages
@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


# ---------------------------------------------------------------------- state
@app.get("/api/state")
async def get_state() -> dict:
    return {
        "inbox": library.list_inbox(),
        "weeks": [w.to_dict() for w in library.list_weeks()],
        "next_week": library.next_week_number(),
        "api_provider": settings.api_provider,
    }


@app.get("/api/diagnostic", response_class=PlainTextResponse)
async def get_diagnostic() -> str:
    return diagnostic().read()


@app.get("/api/week/{week}/file/{name}", response_class=PlainTextResponse)
async def get_week_file(week: int, name: str) -> str:
    # Guard against path traversal; only allow plain filenames.
    if "/" in name or "\\" in name or ".." in name:
        raise HTTPException(400, "Bad filename")
    path = library.week_dir(week) / name
    if not path.exists():
        raise HTTPException(404, f"{name} not found for Week {week:02d}")
    return path.read_text(encoding="utf-8")


# --------------------------------------------------------------------- upload
@app.post("/api/upload")
async def upload(files: list[UploadFile] = File(...), week: str = Form("inbox")) -> dict:
    """Save PDFs to the inbox, or directly into a week's input/ if week is numeric."""
    if week == "new":
        target_week = library.next_week_number()
        dest_dir = library.create_week(target_week) / "input"
    elif week.isdigit():
        target_week = int(week)
        dest_dir = library.create_week(target_week) / "input"
    else:
        target_week = None
        dest_dir = library.inbox

    saved = []
    for f in files:
        if not f.filename.lower().endswith(".pdf"):
            continue
        dest = dest_dir / Path(f.filename).name
        dest.write_bytes(await f.read())
        saved.append(dest.name)
    return {"saved": saved, "week": target_week}


@app.post("/api/assign")
async def assign(payload: dict) -> dict:
    filename = payload.get("filename")
    week_val = payload.get("week", "new")
    week = library.next_week_number() if week_val == "new" else int(week_val)
    try:
        dest = library.assign_inbox_to_week(filename, week)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))
    return {"week": week, "dest": str(dest.relative_to(settings.root))}


# ------------------------------------------------------------------ pipeline
@app.post("/api/ingest")
async def ingest(payload: dict) -> JSONResponse:
    from agents.ingestion_agent import IngestionAgent

    week = int(payload["week"])
    agent = IngestionAgent(settings, router)
    try:
        outputs = await asyncio.to_thread(
            agent.ingest_week, library.week_dir(week), week
        )
    except LLMError as exc:
        return JSONResponse({"error": str(exc)}, status_code=502)
    except (FileNotFoundError, ValueError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse({
        "week": week,
        "tiers": {t: p.name for t, p in outputs.items()},
    })


@app.post("/api/review")
async def review(payload: dict) -> JSONResponse:
    from agents.socratic_dismantler import SocraticDismantler

    week = int(payload["week"])
    essay_path = library.week_dir(week) / "Essay.md"
    agent = SocraticDismantler(settings, router)
    try:
        result = await asyncio.to_thread(
            agent.review, essay_path, week, diagnostic()
        )
    except LLMError as exc:
        return JSONResponse({"error": str(exc)}, status_code=502)
    except (FileNotFoundError, ValueError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse({
        "week": week,
        "critique": result.critique_markdown,
        "findings": result.findings,
        "file": result.critique_path.name,
    })


@app.post("/api/quiz")
async def quiz(payload: dict) -> JSONResponse:
    from agents.quiz_agent import QuizAgent

    week = int(payload["week"])
    agent = QuizAgent(settings, router)
    prior = list(range(1, week))
    try:
        result = await asyncio.to_thread(
            agent.build_quiz, library.week_dir(week), week, prior
        )
    except LLMError as exc:
        return JSONResponse({"error": str(exc)}, status_code=502)
    except (FileNotFoundError, ValueError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse({
        "week": week,
        "quiz": result.quiz_path.name,
        "answers": result.answers_path.name,
        "interleaved": result.interleaved,
    })


# Files the student is allowed to write through the UI.
_SAVABLE = {"Answers.md", "Essay.md"}


@app.post("/api/save")
async def save_file(payload: dict) -> JSONResponse:
    week = int(payload["week"])
    name = str(payload["name"])
    if name not in _SAVABLE:
        raise HTTPException(400, f"Cannot save {name!r}; allowed: {sorted(_SAVABLE)}")
    path = library.create_week(week) / name
    path.write_text(payload.get("content", ""), encoding="utf-8")
    return JSONResponse({"week": week, "saved": name})


@app.post("/api/grade")
async def grade(payload: dict) -> JSONResponse:
    from agents.grader_agent import GraderAgent

    week = int(payload["week"])
    wdir = library.week_dir(week)
    agent = GraderAgent(settings, router)
    try:
        result = await asyncio.to_thread(
            agent.grade, wdir / "Quiz.md", wdir / "Answers.md", week, diagnostic()
        )
    except LLMError as exc:
        return JSONResponse({"error": str(exc)}, status_code=502)
    except (FileNotFoundError, ValueError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse({
        "week": week,
        "feedback": result.feedback_markdown,
        "findings": result.findings,
        "file": result.feedback_path.name,
    })


# ------------------------------------------------------------ feynman (live)
@app.websocket("/ws/feynman/{week}")
async def feynman_ws(ws: WebSocket, week: int) -> None:
    from agents.feynman_pupil import FeynmanPupil

    await ws.accept()
    agent = FeynmanPupil(settings, router)
    diag = diagnostic()
    try:
        convo, opening = await asyncio.to_thread(agent.start, diag, week)
        await ws.send_json({"role": "pupil", "text": opening})

        while True:
            msg = await ws.receive_text()
            if agent.is_end_command(msg):
                break
            reply = await asyncio.to_thread(agent.respond, convo, msg)
            await ws.send_json({"role": "pupil", "text": reply})

        summary = await asyncio.to_thread(agent.finish, convo, week, diag)
        await ws.send_json({"role": "summary", "text": summary})
        await ws.close()
    except WebSocketDisconnect:
        # Save what we have so the session isn't lost.
        await asyncio.to_thread(agent.finish, convo, week, diag)
    except LLMError as exc:
        await ws.send_json({"role": "error", "text": str(exc)})
        await ws.close()


# Mount static assets last so /api and /ws take precedence.
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
