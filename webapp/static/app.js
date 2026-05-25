"use strict";

const $ = (sel) => document.querySelector(sel);
const el = (tag, cls, txt) => { const e = document.createElement(tag); if (cls) e.className = cls; if (txt != null) e.textContent = txt; return e; };

const HAS_MARKED = typeof window.marked !== "undefined";
if (typeof window.mermaid !== "undefined") {
  mermaid.initialize({ startOnLoad: false, theme: "default" });
}

let state = { inbox: [], weeks: [], next_week: 1, api_provider: "" };
let ws = null, chatWeek = null;

// ----------------------------------------------------------------- utilities
function toast(msg) {
  const t = $("#toast"); t.textContent = msg; t.classList.add("show");
  setTimeout(() => t.classList.remove("show"), 2600);
}

async function api(path, opts) {
  const res = await fetch(path, opts);
  let data = null;
  try { data = await res.json(); } catch (_) {}
  if (!res.ok) throw new Error((data && data.error) || `${res.status} ${res.statusText}`);
  return data;
}

async function renderMarkdown(container, md) {
  if (!HAS_MARKED) { container.innerHTML = ""; container.appendChild(el("pre", null, md)); return; }
  container.innerHTML = marked.parse(md);
  // Convert ```mermaid blocks into rendered diagrams.
  const blocks = container.querySelectorAll("code.language-mermaid");
  if (blocks.length && typeof window.mermaid !== "undefined") {
    blocks.forEach((code) => {
      const div = el("div", "mermaid"); div.textContent = code.textContent;
      code.closest("pre").replaceWith(div);
    });
    try { await mermaid.run({ nodes: container.querySelectorAll(".mermaid") }); } catch (_) {}
  }
}

// -------------------------------------------------------------------- render
async function refresh() {
  state = await api("/api/state");
  $("#provider").textContent = `API: ${state.api_provider} · local: Ollama`;
  renderInbox(); renderWeeks();
}

function renderInbox() {
  const ul = $("#inbox"); ul.innerHTML = "";
  $("#inbox-count").textContent = state.inbox.length ? `(${state.inbox.length})` : "";
  if (!state.inbox.length) { ul.appendChild(el("li", "empty-note", "Empty — drop PDFs above.")); return; }
  state.inbox.forEach((name) => {
    const li = el("li", "card");
    const row = el("div", "row");
    row.appendChild(el("span", "name", "📄 " + name));
    const btn = el("button", "mini primary", `Study → Week ${String(state.next_week).padStart(2, "0")}`);
    btn.onclick = async () => {
      await api("/api/assign", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ filename: name, week: "new" }) });
      toast(`Assigned to a new week. Now Ingest it.`); refresh();
    };
    row.appendChild(btn); li.appendChild(row); ul.appendChild(li);
  });
}

function renderWeeks() {
  const ul = $("#weeks"); ul.innerHTML = "";
  if (!state.weeks.length) { ul.appendChild(el("li", "empty-note", "No weeks yet.")); return; }
  state.weeks.forEach((w) => {
    const li = el("li", "card");
    const row = el("div", "row");
    const left = el("div");
    left.appendChild(el("span", "name", `Week ${String(w.week).padStart(2, "0")}`));
    const files = [...w.tiers,
      w.has_quiz ? "Quiz.md" : null, w.has_answers ? "Answers.md" : null,
      w.has_feedback ? "Feedback.md" : null, w.has_essay ? "Essay.md" : null,
      w.has_critique ? "Critique.md" : null].filter(Boolean);
    left.appendChild(el("div", "sub", w.pdfs.length ? w.pdfs.join(", ") : "no PDFs"));
    row.appendChild(left);
    row.appendChild(el("span", "badge " + w.status, w.status));
    li.appendChild(row);

    // openable file chips
    if (files.length) {
      const chips = el("div", "sub");
      files.forEach((f) => {
        const c = el("button", "chip-file", f);
        c.onclick = () => openFile(w.week, f);
        chips.appendChild(c);
      });
      li.appendChild(chips);
    }

    // actions
    const acts = el("div", "actions");
    acts.appendChild(actionBtn("Ingest", (btn) => runIngest(w.week, btn), !w.pdfs.length));
    acts.appendChild(actionBtn("Quiz", () => openQuiz(w.week), !w.tiers.length));
    acts.appendChild(actionBtn("Review", (btn) => runReview(w.week, btn), !w.has_essay));
    acts.appendChild(actionBtn("Feynman", () => startChat(w.week)));
    li.appendChild(acts); ul.appendChild(li);
  });
}

function actionBtn(label, fn, disabled) {
  const b = el("button", "mini", label); b.disabled = !!disabled;
  if (!disabled) b.onclick = () => fn(b);
  return b;
}

async function withSpinner(btn, fn) {
  const original = btn ? btn.innerHTML : null;
  if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>'; }
  try { return await fn(); }
  finally { if (btn) { btn.disabled = false; btn.innerHTML = original; } }
}

// ------------------------------------------------------------------ actions
async function runIngest(week, btn) {
  toast(`Ingesting Week ${week}… (may take a minute)`);
  try {
    await withSpinner(btn, () => api("/api/ingest", jsonBody({ week })));
    toast(`Week ${week} ingested.`); await refresh(); openFile(week, "Beginner.md");
  } catch (e) { toast("Ingest failed: " + e.message); }
}

async function runReview(week, btn) {
  toast(`Socratic review of Week ${week}…`);
  try {
    const r = await withSpinner(btn, () => api("/api/review", jsonBody({ week })));
    toast(`Critique ready · ${r.findings.length} finding(s) logged.`); await refresh();
    openFile(week, r.file);
  } catch (e) { toast("Review failed: " + e.message); }
}

function jsonBody(obj) {
  return { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(obj) };
}

// ------------------------------------------------------------------- viewer
function showView(name) {
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.view === name));
  document.querySelectorAll(".view").forEach((v) => v.classList.toggle("active", v.id === name));
}

async function openFile(week, name) {
  showView("viewer");
  $("#viewer-title").textContent = `Week ${String(week).padStart(2, "0")} · ${name}`;
  try {
    const md = await (await fetch(`/api/week/${week}/file/${name}`)).text();
    renderMarkdown($("#viewer-body"), md);
  } catch (e) { $("#viewer-body").textContent = "Could not load file."; }
}

async function openDiagnostic() {
  showView("viewer");
  $("#viewer-title").textContent = "state/Diagnostic.md";
  const md = await (await fetch("/api/diagnostic")).text();
  renderMarkdown($("#viewer-body"), md);
}

// ---------------------------------------------------------------------- quiz
let quizWeek = null;
const weekInfo = (week) => state.weeks.find((w) => w.week === week) || {};

async function fetchFile(week, name) {
  const r = await fetch(`/api/week/${week}/file/${name}`);
  return r.ok ? r.text() : "";
}

async function openQuiz(week) {
  showView("quiz");
  quizWeek = week;
  $("#quiz-header").innerHTML = `📝 <strong>Week ${String(week).padStart(2, "0")} Quiz</strong>`;
  const w = weekInfo(week);
  if (!w.has_quiz) {
    $("#quiz-empty").classList.remove("hidden");
    $("#quiz-body").classList.add("hidden");
    return;
  }
  $("#quiz-empty").classList.add("hidden");
  $("#quiz-body").classList.remove("hidden");
  renderMarkdown($("#quiz-questions"), await fetchFile(week, "Quiz.md"));
  $("#quiz-answers").value = w.has_answers ? await fetchFile(week, "Answers.md") : "";
  $("#quiz-essay").value = w.has_essay ? await fetchFile(week, "Essay.md") : "";
  if (w.has_feedback) renderMarkdown($("#quiz-feedback"), await fetchFile(week, "Feedback.md"));
  else $("#quiz-feedback").innerHTML = "";
}

async function saveQuizFile(name, content, btn) {
  const fn = () => api("/api/save", jsonBody({ week: quizWeek, name, content }));
  return btn ? withSpinner(btn, fn) : fn();
}

$("#quiz-generate").onclick = async (e) => {
  toast(`Generating Week ${quizWeek} quiz… (may take a minute)`);
  try {
    await withSpinner(e.target, () => api("/api/quiz", jsonBody({ week: quizWeek })));
    await refresh(); openQuiz(quizWeek); toast("Quiz ready.");
  } catch (err) { toast("Quiz failed: " + err.message); }
};

$("#quiz-save").onclick = async (e) => {
  try { await saveQuizFile("Answers.md", $("#quiz-answers").value, e.target); toast("Answers saved."); }
  catch (err) { toast("Save failed: " + err.message); }
};

$("#quiz-essay-save").onclick = async (e) => {
  try {
    await saveQuizFile("Essay.md", $("#quiz-essay").value, e.target);
    await refresh(); toast("Essay saved — Review is now available on this week.");
  } catch (err) { toast("Save failed: " + err.message); }
};

$("#quiz-grade").onclick = async (e) => {
  try {
    await saveQuizFile("Answers.md", $("#quiz-answers").value, null);
    toast(`Grading Week ${quizWeek}…`);
    const r = await withSpinner(e.target, () => api("/api/grade", jsonBody({ week: quizWeek })));
    renderMarkdown($("#quiz-feedback"), r.feedback);
    await refresh();
    toast(`Feedback ready · ${r.findings.length} finding(s) logged.`);
  } catch (err) { toast("Grading failed: " + err.message); }
};

// --------------------------------------------------------------------- chat
function startChat(week) {
  showView("chat");
  chatWeek = week;
  $("#chat-header").textContent = `🧒 Feynman Pupil · Week ${String(week).padStart(2, "0")} — teach until it clicks. /done to end.`;
  $("#chat-log").innerHTML = "";
  if (ws) { try { ws.close(); } catch (_) {} }
  ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/feynman/${week}`);
  setChatEnabled(false);
  addBubble("sys", "Connecting to the pupil…");

  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.role === "pupil") { addBubble("pupil", m.text); setChatEnabled(true); }
    else if (m.role === "summary") { addBubble("sys", "Session summary saved to Diagnostic.md."); setChatEnabled(false); refresh(); }
    else if (m.role === "error") { addBubble("err", m.text); setChatEnabled(false); }
  };
  ws.onclose = () => setChatEnabled(false);
  ws.onerror = () => addBubble("err", "Connection error. Is the server running?");
}

function setChatEnabled(on) {
  $("#chat-input").disabled = !on; $("#chat-send").disabled = !on;
  if (on) $("#chat-input").focus();
}

function addBubble(kind, text) {
  const b = el("div", "bubble " + kind, text);
  $("#chat-log").appendChild(b);
  $("#chat-log").scrollTop = $("#chat-log").scrollHeight;
}

$("#chat-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const input = $("#chat-input"); const text = input.value.trim();
  if (!text || !ws || ws.readyState !== 1) return;
  const isEnd = ["/done", "/quit", "/exit"].includes(text.toLowerCase());
  if (!isEnd) addBubble("me", text); else addBubble("sys", "Ending session…");
  ws.send(text); input.value = "";
  if (!isEnd) setChatEnabled(false);  // wait for pupil reply
});

// ------------------------------------------------------------------- upload
function uploadFiles(fileList) {
  const fd = new FormData();
  let n = 0;
  [...fileList].forEach((f) => { if (f.name.toLowerCase().endsWith(".pdf")) { fd.append("files", f); n++; } });
  if (!n) { toast("Only PDF files are accepted."); return; }
  fd.append("week", "inbox");
  fetch("/api/upload", { method: "POST", body: fd })
    .then((r) => r.json())
    .then(() => { toast(`Uploaded ${n} PDF(s) to inbox.`); refresh(); })
    .catch((e) => toast("Upload failed: " + e.message));
}

function wireUpload() {
  const dz = $("#dropzone"), fi = $("#fileinput");
  dz.onclick = () => fi.click();
  fi.onchange = () => { if (fi.files.length) uploadFiles(fi.files); fi.value = ""; };
  ["dragenter", "dragover"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add("drag"); }));
  ["dragleave", "drop"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove("drag"); }));
  dz.addEventListener("drop", (e) => uploadFiles(e.dataTransfer.files));
}

// --------------------------------------------------------------------- init
document.querySelectorAll(".tab[data-view]").forEach((t) => t.onclick = () => showView(t.dataset.view));
$("#open-diagnostic").onclick = openDiagnostic;
wireUpload();
refresh();
