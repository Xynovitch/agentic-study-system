# CLAUDE.md — Agentic Study System

Persistent project context for future agentic sessions. Read this first.

## What this is
A local, multi-agent "Agentic Study System" that ingests a bilingual (English/Korean)
"Introduction to Computer Science" curriculum and runs it through three pedagogical phases:
Synthesis → Retention → Review. State and study materials are plain Markdown.

## Hybrid LLM routing (deterministic table)
The router table lives in **`config.yaml`**; never hard-code models in agents.

| Logical engine | Resolves to | Role | Used by |
|----------------|-------------|------|---------|
| `api` | Anthropic **or** OpenAI (set by `API_PROVIDER` in `.env`) | Heavy Lifter — large context, EN/KO translation, vision for slides | ingestion, web_explorer, quiz, grader, **socratic_dismantler** |
| `ollama` | local model named in `config.yaml` (default `qwen2.5:7b`) | Fast Chatter — low-latency conversational loops | **feynman_pupil** |

- All model calls go through `core/llm_router.py::LLMRouter.chat(...)`. Add backends there.
- `core/config.py` resolves the logical `api` engine into a concrete provider + model.
- To make an agent tougher/cheaper, edit only its `config.yaml` entry (engine/model/temperature).

## API key & environment structure
Copy `.env.example` → `.env` (git-ignored) and set:

| Var | Purpose |
|-----|---------|
| `ANTHROPIC_API_KEY` | Claude access (if `API_PROVIDER=anthropic`) |
| `OPENAI_API_KEY` | GPT access (if `API_PROVIDER=openai`) |
| `API_PROVIDER` | `anthropic` \| `openai` — which provider the `api` engine uses |
| `OLLAMA_HOST` | Ollama endpoint (default `http://localhost:11434`) |

The Feynman Pupil runs fully offline on Ollama and needs **no** API key.

## Pedagogical invariants (enforced, not hoped for)
These are checked in code by `core/validators.py` and re-prompted via
`BaseAgent.run_validated`. Do not weaken them.
1. **Cognitive Load** — broad concepts vs hardware specifics live in separate tier files
   (`Beginner.md` / `Intermediate.md` / `Advanced.md`).
2. **Dual Coding** — every synthesis file contains at least one `mermaid` diagram
   (`has_mermaid_block`).
3. **Worked-Example Effect** — a solved step-by-step example precedes any abstract rule
   (`worked_example_before_rules`).
4. **Bilingual Integrity** — output is English; the exact Korean term sits in parentheses
   right after the English term, e.g. `binary (이진법)` (`korean_in_parentheses`).
5. **Metacognitive Scaffolding** — never "Correct/Incorrect"; trace where the mental model
   broke down (`no_binary_grading`).

## Interfaces
- **Web launcher** (`python main.py serve`, default port 8000): FastAPI app in `webapp/`.
  Drop PDFs → inbox (`study/inbox/`) → "Study → Week NN" assigns them → per-week Ingest / Quiz /
  Review / Feynman buttons (Quiz tab handles answers + grading). Long LLM calls run via
  `asyncio.to_thread`; Feynman chat is a WebSocket
  (`/ws/feynman/{week}`). Frontend is dependency-free vanilla JS in `webapp/static/`.
- **CLI** (`python main.py <cmd>`): same agents, no browser.

## Workflow
1. **Phase 1 — Synthesis** (`ingest --week N` / Ingest button): parse `Week_NN/input/*.pdf`
   (text + rendered page images) → three tiered notes via the vision API. **Implemented.**
   Real web image search for diagrams is still TODO; Mermaid satisfies Dual Coding meanwhile.
2. **Phase 2 — Retention** (`quiz --week N`, then `grade --week N` / Quiz tab): tiered quiz
   (MCQ/cloze → application/logic → essay prompt) with a 20%-interleaved review section
   (`require_interleaving`); writes `Quiz.md` + a blank `Answers.md`. The grader writes
   `Feedback.md` tracing where reasoning diverges (never grades) and logs findings to
   `Diagnostic.md`. **Implemented.**
3. **Phase 3 — Review** (implemented):
   - **Agent A** `review --week N [--essay PATH]` — Socratic Dismantler attacks the Advanced
     essay, writes `Critique.md`, appends flaws to `state/Diagnostic.md`.
   - **Agent B** `feynman --week N [--model M]` — Feynman Pupil reads `Diagnostic.md` and runs a
     teach-back loop (terminal or WebSocket); appends a session summary.

## Subjects (top-level grouping)
Weeks live under a **subject**: `curriculum/<slug>/Week_NN/`. A subject folder holds a
`subject.json` ({"name": ...}; the slug folder name never changes on rename) and its own
`Diagnostic.md`. `core/library.py` splits this into `Library` (scoped to one subject, via
`Library(root, slug)`) and `SubjectStore` (list/create/rename/delete subjects).
`ensure_migrated()` runs at server/CLI startup and folds any legacy flat `curriculum/Week_NN/`
(+ old `state/Diagnostic.md`) into a default subject — idempotent. The inbox is **shared** across
subjects. The web server tracks one active subject (`/api/subject/{create,select,rename,delete}`);
CLI week commands take `--subject SLUG|NAME` (default: first subject).

## State files
- `curriculum/<slug>/Diagnostic.md` — per-subject evolving strengths/weaknesses/gaps +
  append-only Findings Log. Shared memory between Agent A and Agent B; auto-created from template.
- `curriculum/<slug>/Week_NN/` — per-week `input/`, tier notes, `assets/`, `Quiz.md`, `Essay.md`,
  `Critique.md`, plus a `meta.json` for the optional week display title.

## Context discipline
Agents are independent and exchange **file paths + short summaries**, never raw essays/slides,
so the orchestrator's context window stays small. Keep it that way when extending.

## Layout
```
core/      config, llm_router (multimodal), base_agent, validators, pdf_parser, state, library
agents/    ingestion, quiz, grader, socratic_dismantler, feynman_pupil (live) · web_explorer (stub)
prompts/   per-agent system prompts (rules encoded in prose)
webapp/    server.py (FastAPI) + static/ (index.html, app.js, style.css)
study/inbox/                   shared drop-zone for new PDFs
curriculum/<slug>/             one subject: subject.json + Diagnostic.md + weeks
curriculum/<slug>/Week_NN/     per-week inputs & outputs (+ meta.json title)
config.yaml  routing table   ·   main.py  CLI + `serve`
```

## Conventions for future edits
- New agent → add a `config.yaml` entry, subclass `BaseAgent`, put rules in a `prompts/*.md`.
- New rule → add a `Validator` in `core/validators.py` and include it in the agent's bundle.
- New backend → extend `LLMRouter.chat`; keep the uniform `(messages, engine, model, system,
  temperature)` signature.
