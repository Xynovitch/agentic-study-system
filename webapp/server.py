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
from core.library import Library, SubjectStore, ensure_migrated
from core.llm_router import LLMError, make_router
from core.state import Diagnostic

settings = load_settings()
router = make_router(settings)

ensure_migrated(settings.root)            # move any pre-subject layout into a default subject
subjects = SubjectStore(settings.root)
inbox_lib = Library(settings.root)        # subject-agnostic; used only for the shared inbox
_active: dict[str, str | None] = {"subject": None}

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="Agentic Study System")


def current_subject() -> str | None:
    """The active subject slug, defaulting to the first available one."""
    slugs = [s.slug for s in subjects.list_subjects()]
    if _active["subject"] not in slugs:
        _active["subject"] = slugs[0] if slugs else None
    return _active["subject"]


def get_library() -> Library:
    """Library scoped to the active subject (400 if none exists yet)."""
    slug = current_subject()
    if slug is None:
        raise HTTPException(400, "No subject yet. Create one first.")
    return Library(settings.root, slug)


def diagnostic() -> Diagnostic:
    return Diagnostic.open(get_library().diagnostic_path())


def _safe_name(name: str) -> str:
    """Reject path-traversal in a user-supplied filename; return it unchanged."""
    if not name or "/" in name or "\\" in name or ".." in name:
        raise HTTPException(400, "Bad filename")
    return name


# --------------------------------------------------------------------- pages
@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


# ---------------------------------------------------------------------- state
@app.get("/api/state")
async def get_state() -> dict:
    slug = current_subject()
    lib = Library(settings.root, slug) if slug else None
    return {
        "subjects": [s.to_dict() for s in subjects.list_subjects()],
        "subject": slug,
        "inbox": inbox_lib.list_inbox(),
        "weeks": [w.to_dict() for w in lib.list_weeks()] if lib else [],
        "next_week": lib.next_week_number() if lib else 1,
        "api_provider": settings.api_provider,
    }


# -------------------------------------------------------------------- subjects
@app.post("/api/subject/create")
async def subject_create(payload: dict) -> dict:
    try:
        slug = subjects.create_subject(str(payload.get("name", "")))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    _active["subject"] = slug
    return {"slug": slug, "name": str(payload.get("name", "")).strip()}


@app.post("/api/subject/select")
async def subject_select(payload: dict) -> dict:
    slug = str(payload.get("slug", ""))
    if not subjects.exists(slug):
        raise HTTPException(404, f"Subject not found: {slug}")
    _active["subject"] = slug
    return {"slug": slug}


@app.post("/api/subject/rename")
async def subject_rename(payload: dict) -> dict:
    slug = str(payload["slug"])
    try:
        name = subjects.rename_subject(slug, str(payload.get("name", "")))
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"slug": slug, "name": name}


@app.post("/api/subject/delete")
async def subject_delete(payload: dict) -> dict:
    slug = str(payload["slug"])
    try:
        subjects.delete_subject(slug)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))
    if _active["subject"] == slug:
        _active["subject"] = None
    return {"deleted": slug}


@app.get("/api/diagnostic", response_class=PlainTextResponse)
async def get_diagnostic() -> str:
    return diagnostic().read()


@app.get("/api/week/{week}/file/{name}", response_class=PlainTextResponse)
async def get_week_file(week: int, name: str) -> str:
    # Guard against path traversal; only allow plain filenames.
    _safe_name(name)
    path = get_library().week_dir(week) / name
    if not path.exists():
        raise HTTPException(404, f"{name} not found for Week {week:02d}")
    return path.read_text(encoding="utf-8")


# --------------------------------------------------------------------- upload
@app.post("/api/upload")
async def upload(files: list[UploadFile] = File(...), week: str = Form("inbox")) -> dict:
    """Save PDFs to the inbox, or directly into a week's input/ if week is numeric."""
    if week == "new":
        lib = get_library()
        target_week = lib.next_week_number()
        dest_dir = lib.create_week(target_week) / "input"
    elif week.isdigit():
        target_week = int(week)
        dest_dir = get_library().create_week(target_week) / "input"
    else:
        target_week = None
        dest_dir = inbox_lib.inbox

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
    """Assign one or more inbox PDFs into a SINGLE week (new or existing).

    Accepts ``filenames`` (a list) or legacy ``filename`` (a single string).
    ``week`` is ``"new"`` to mint the next week, or a week number to add to an
    existing one.
    """
    filenames = payload.get("filenames")
    if filenames is None:
        single = payload.get("filename")
        filenames = [single] if single else []
    filenames = [f for f in filenames if f]
    if not filenames:
        raise HTTPException(400, "No PDFs selected to assign.")

    lib = get_library()
    week_val = payload.get("week", "new")
    week = lib.next_week_number() if week_val == "new" else int(week_val)
    try:
        dests = lib.assign_many(filenames, week)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))
    return {"week": week, "assigned": [d.name for d in dests]}


# ------------------------------------------------------------------- modify
@app.post("/api/week/rename")
async def week_rename(payload: dict) -> dict:
    week = int(payload["week"])
    title = get_library().set_title(week, str(payload.get("title", "")))
    return {"week": week, "title": title}


@app.post("/api/pdf/move")
async def pdf_move(payload: dict) -> dict:
    from_week = int(payload["from_week"])
    filename = _safe_name(str(payload["filename"]))
    to = payload["to"]
    to_val = "inbox" if to == "inbox" else int(to)
    try:
        dest = get_library().move_pdf(filename, from_week, to_val)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))
    return {"moved": dest.name, "to": str(to_val)}


@app.post("/api/pdf/delete")
async def pdf_delete(payload: dict) -> dict:
    week = int(payload["week"])
    filename = _safe_name(str(payload["filename"]))
    try:
        get_library().delete_pdf(week, filename)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))
    return {"week": week, "deleted": filename}


@app.post("/api/week/delete")
async def week_delete(payload: dict) -> dict:
    week = int(payload["week"])
    try:
        get_library().delete_week(week)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))
    return {"deleted": week}


@app.post("/api/week/merge")
async def week_merge(payload: dict) -> dict:
    source = int(payload["source"])
    target = int(payload["target"])
    try:
        moved = get_library().merge_weeks(source, target)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"source": source, "target": target, "moved": moved}


# ------------------------------------------------------------------ pipeline
@app.post("/api/ingest")
async def ingest(payload: dict) -> JSONResponse:
    from agents.ingestion_agent import IngestionAgent

    week = int(payload["week"])
    agent = IngestionAgent(settings, router)
    try:
        outputs = await asyncio.to_thread(
            agent.ingest_week, get_library().week_dir(week), week
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
    essay_path = get_library().week_dir(week) / "Essay.md"
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
            agent.build_quiz, get_library().week_dir(week), week, prior
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
    path = get_library().create_week(week) / name
    path.write_text(payload.get("content", ""), encoding="utf-8")
    return JSONResponse({"week": week, "saved": name})


@app.post("/api/grade")
async def grade(payload: dict) -> JSONResponse:
    from agents.grader_agent import GraderAgent

    week = int(payload["week"])
    wdir = get_library().week_dir(week)
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
