"use strict";

const $ = (sel) => document.querySelector(sel);
const el = (tag, cls, txt) => { const e = document.createElement(tag); if (cls) e.className = cls; if (txt != null) e.textContent = txt; return e; };

const HAS_MARKED = typeof window.marked !== "undefined";
if (typeof window.mermaid !== "undefined") {
  mermaid.initialize({ startOnLoad: false, theme: "default" });
}

let state = { subjects: [], subject: null, inbox: [], weeks: [], next_week: 1, api_provider: "" };
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

// Mermaid treats an unquoted "(" inside a node label as round-node syntax, so
// labels like [machine language (기계어)] — which our bilingual notes produce
// constantly — are syntax errors and the whole diagram silently fails. Quote any
// [ ] or { } node label that contains parentheses and isn't already quoted.
function sanitizeMermaid(src) {
  return src.replace(
    /([\[{])([^\[\]{}"][^\[\]{}]*?)([\]}])/g,
    (m, open, label, close) =>
      /[()]/.test(label) ? `${open}"${label.replace(/"/g, "'")}"${close}` : m
  );
}

async function renderMarkdown(container, md) {
  if (!HAS_MARKED) { container.innerHTML = ""; container.appendChild(el("pre", null, md)); return; }
  container.innerHTML = marked.parse(md);
  // Convert ```mermaid blocks into rendered diagrams.
  const blocks = container.querySelectorAll("code.language-mermaid");
  if (!blocks.length || typeof window.mermaid === "undefined") return;
  const divs = [];
  blocks.forEach((code) => {
    const div = el("div", "mermaid"); div.textContent = sanitizeMermaid(code.textContent);
    code.closest("pre").replaceWith(div); divs.push(div);
  });
  // Render each diagram in isolation so one malformed diagram can't blank the rest.
  for (const div of divs) {
    const src = div.textContent;
    try {
      await mermaid.run({ nodes: [div] });
    } catch (_) {
      div.classList.add("mermaid-error");
      div.textContent = "⚠ diagram could not be rendered";
      const pre = el("pre", "mermaid-src", src); div.after(pre);
    }
  }
}

// -------------------------------------------------------------------- render
async function refresh() {
  state = await api("/api/state");
  $("#provider").textContent = `API: ${state.api_provider} · local: Ollama`;
  renderSubjects(); renderInbox(); renderWeeks();
}

// --------------------------------------------------------------- subjects
function renderSubjects() {
  const sel = $("#subject-select"); sel.innerHTML = "";
  const has = state.subjects.length > 0;
  if (!has) {
    const o = el("option", null, "No subjects — click ＋"); o.value = ""; sel.appendChild(o);
  }
  state.subjects.forEach((s) => {
    const o = el("option", null, `${s.name} (${s.weeks} wk)`); o.value = s.slug;
    if (s.slug === state.subject) o.selected = true;
    sel.appendChild(o);
  });
  sel.disabled = !has;
  $("#subject-rename").disabled = !has;
  $("#subject-delete").disabled = !has;
}

async function selectSubject(slug) {
  try { await api("/api/subject/select", jsonBody({ slug })); await refresh(); }
  catch (e) { toast("Switch failed: " + e.message); }
}

async function newSubject() {
  const name = (prompt("New subject name (e.g. Linear Algebra (선형대수)):") || "").trim();
  if (!name) return;
  try { await api("/api/subject/create", jsonBody({ name })); toast(`Subject “${name}” created.`); await refresh(); }
  catch (e) { toast("Create failed: " + e.message); }
}

async function renameSubject() {
  if (!state.subject) return;
  const cur = (state.subjects.find((s) => s.slug === state.subject) || {}).name || "";
  const name = (prompt("Rename subject:", cur) || "").trim();
  if (!name || name === cur) return;
  try { await api("/api/subject/rename", jsonBody({ slug: state.subject, name })); toast("Subject renamed."); await refresh(); }
  catch (e) { toast("Rename failed: " + e.message); }
}

async function deleteSubject() {
  if (!state.subject) return;
  const cur = (state.subjects.find((s) => s.slug === state.subject) || {});
  if (!confirm(`Delete subject “${cur.name}” and ALL ${cur.weeks} week(s)? This cannot be undone.`)) return;
  try { await api("/api/subject/delete", jsonBody({ slug: state.subject })); toast("Subject deleted."); await refresh(); }
  catch (e) { toast("Delete failed: " + e.message); }
}

function renderInbox() {
  const ul = $("#inbox"); ul.innerHTML = "";
  const bar = $("#inbox-bar");
  $("#inbox-count").textContent = state.inbox.length ? `(${state.inbox.length})` : "";
  $("#inbox-all").checked = false;
  if (!state.inbox.length) {
    ul.appendChild(el("li", "empty-note", "Empty — drop PDFs above."));
    bar.classList.add("hidden");
    return;
  }
  bar.classList.remove("hidden");
  state.inbox.forEach((name) => {
    const li = el("li", "card");
    const lab = el("label", "inbox-pick");
    const cb = el("input"); cb.type = "checkbox"; cb.className = "inbox-cb"; cb.value = name;
    lab.appendChild(cb);
    lab.appendChild(el("span", "name", "📄 " + name));
    li.appendChild(lab); ul.appendChild(li);
  });
  renderInboxTarget();
}

// Populate the assign-target dropdown: a fresh week, or any existing week.
function renderInboxTarget() {
  const sel = $("#inbox-target"); sel.innerHTML = "";
  const wk = (n) => `Week ${String(n).padStart(2, "0")}`;
  const optNew = el("option", null, `→ New ${wk(state.next_week)}`); optNew.value = "new";
  sel.appendChild(optNew);
  state.weeks.forEach((w) => {
    const o = el("option", null, `→ Add to ${wk(w.week)}`); o.value = String(w.week);
    sel.appendChild(o);
  });
}

async function assignSelected() {
  if (!state.subject) { toast("Create a subject first (＋)."); return; }
  const checked = [...document.querySelectorAll(".inbox-cb:checked")].map((c) => c.value);
  if (!checked.length) { toast("Select at least one PDF first."); return; }
  const target = $("#inbox-target").value;
  try {
    const r = await api("/api/assign", jsonBody({ filenames: checked, week: target }));
    const wk = String(r.week).padStart(2, "0");
    toast(`Assigned ${r.assigned.length} PDF(s) → Week ${wk}. (Re-)Ingest to fold them in.`);
    refresh();
  } catch (e) { toast("Assign failed: " + e.message); }
}

function renderWeeks() {
  const ul = $("#weeks"); ul.innerHTML = "";
  $("#weeks-all").checked = false;
  if (!state.weeks.length) {
    ul.appendChild(el("li", "empty-note", "No weeks yet."));
    $("#weeks-bar").classList.add("hidden");
    return;
  }
  $("#weeks-bar").classList.remove("hidden");
  state.weeks.forEach((w) => {
    const li = el("li", "card");
    const row = el("div", "row");
    const head = el("div", "wk-head");
    const cb = el("input"); cb.type = "checkbox"; cb.className = "week-cb"; cb.value = String(w.week);
    head.appendChild(cb);
    const left = el("div");
    const wkLabel = `Week ${String(w.week).padStart(2, "0")}`;
    left.appendChild(el("span", "name", w.title || wkLabel));
    const files = [...w.tiers,
      w.has_diagrams ? "Diagrams.md" : null,
      w.has_quiz ? "Quiz.md" : null, w.has_answers ? "Answers.md" : null,
      w.has_feedback ? "Feedback.md" : null, w.has_essay ? "Essay.md" : null,
      w.has_critique ? "Critique.md" : null].filter(Boolean);
    const subBits = w.title ? [wkLabel] : [];
    subBits.push(w.pdfs.length ? w.pdfs.join(", ") : "no PDFs");
    left.appendChild(el("div", "sub", subBits.join(" · ")));
    head.appendChild(left);
    row.appendChild(head);
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
    acts.appendChild(actionBtn("Diagrams", (btn) => runExplore(w.week, btn), !w.tiers.length));
    acts.appendChild(actionBtn("Quiz", () => openQuiz(w.week), !w.tiers.length));
    acts.appendChild(actionBtn("Review", (btn) => runReview(w.week, btn), !w.has_essay));
    acts.appendChild(actionBtn("Debate", () => startDebate(w.week), !w.has_essay));
    acts.appendChild(actionBtn("Feynman", () => startChat(w.week)));
    const manage = buildManage(w, wkLabel); manage.classList.add("hidden");
    acts.appendChild(actionBtn("Edit", () => manage.classList.toggle("hidden")));
    const delBtn = el("button", "mini danger", "Delete");
    delBtn.onclick = () => deleteWeek(w, wkLabel);
    acts.appendChild(delBtn);
    li.appendChild(acts);
    li.appendChild(manage);
    ul.appendChild(li);
  });
}

// Per-week management: rename, move/delete PDFs, merge into another week, delete.
function buildManage(w, wkLabel) {
  const box = el("div", "wk-manage");
  const others = state.weeks.filter((o) => o.week !== w.week);
  const wkName = w.title || wkLabel;
  const labelOf = (o) => o.title || `Week ${String(o.week).padStart(2, "0")}`;

  // rename (sets a display title; folder stays Week_NN)
  const rRow = el("div", "mng-row");
  const ti = el("input", "mng-input"); ti.type = "text"; ti.value = w.title || ""; ti.placeholder = wkLabel;
  const rb = el("button", "mini", "Rename");
  rb.onclick = async () => {
    try { await api("/api/week/rename", jsonBody({ week: w.week, title: ti.value })); toast("Renamed."); refresh(); }
    catch (e) { toast("Rename failed: " + e.message); }
  };
  rRow.appendChild(ti); rRow.appendChild(rb); box.appendChild(rRow);

  // each PDF: move elsewhere / delete
  w.pdfs.forEach((name) => {
    const row = el("div", "mng-row");
    row.appendChild(el("span", "mng-file", "📄 " + name));
    const sel = el("select", "mini-select");
    const d = el("option", null, "Move…"); d.value = ""; d.disabled = true; d.selected = true; sel.appendChild(d);
    const inb = el("option", null, "↩ Inbox"); inb.value = "inbox"; sel.appendChild(inb);
    others.forEach((o) => { const op = el("option", null, "→ " + labelOf(o)); op.value = String(o.week); sel.appendChild(op); });
    sel.onchange = async () => {
      if (!sel.value) return;
      try { await api("/api/pdf/move", jsonBody({ from_week: w.week, filename: name, to: sel.value })); toast(`Moved ${name}.`); refresh(); }
      catch (e) { toast("Move failed: " + e.message); sel.value = ""; }
    };
    row.appendChild(sel);
    const del = el("button", "mini danger", "🗑"); del.title = "Delete this PDF";
    del.onclick = async () => {
      if (!confirm(`Delete "${name}" from ${wkName}?`)) return;
      try { await api("/api/pdf/delete", jsonBody({ week: w.week, filename: name })); toast("PDF deleted."); refresh(); }
      catch (e) { toast("Delete failed: " + e.message); }
    };
    row.appendChild(del); box.appendChild(row);
  });

  // week-level: merge into another week / delete this week
  const wRow = el("div", "mng-row");
  const msel = el("select", "mini-select");
  const md = el("option", null, "Merge into…"); md.value = ""; md.disabled = true; md.selected = true; msel.appendChild(md);
  others.forEach((o) => { const op = el("option", null, "⛙ " + labelOf(o)); op.value = String(o.week); msel.appendChild(op); });
  if (!others.length) msel.disabled = true;
  msel.onchange = async () => {
    if (!msel.value) return;
    const t = state.weeks.find((o) => String(o.week) === msel.value) || {};
    const tName = labelOf(t);
    if (!confirm(`Merge ${wkName} into ${tName}? Its PDFs move over; ${wkName} and its notes/quiz are removed.`)) { msel.value = ""; return; }
    try { const r = await api("/api/week/merge", jsonBody({ source: w.week, target: msel.value })); toast(`Merged ${r.moved} PDF(s) into ${tName}.`); refresh(); }
    catch (e) { toast("Merge failed: " + e.message); msel.value = ""; }
  };
  wRow.appendChild(msel);
  const delWk = el("button", "mini danger", "Delete week");
  delWk.onclick = async () => {
    if (!confirm(`Delete ${wkName} and ALL its contents? This cannot be undone.`)) return;
    try { await api("/api/week/delete", jsonBody({ week: w.week })); toast(`${wkName} deleted.`); refresh(); }
    catch (e) { toast("Delete failed: " + e.message); }
  };
  wRow.appendChild(delWk); box.appendChild(wRow);

  return box;
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

async function runExplore(week, btn) {
  toast(`Searching Wikimedia Commons for Week ${week} diagrams…`);
  try {
    const r = await withSpinner(btn, () => api("/api/explore", jsonBody({ week })));
    toast(r.count ? `Diagrams: ${r.count} image(s) found.` : "No web diagrams found (Mermaid still covers it).");
    await refresh(); openFile(week, r.file);
  } catch (e) { toast("Diagram search failed: " + e.message); }
}

function jsonBody(obj) {
  return { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(obj) };
}

// ------------------------------------------------------------- bulk actions
// Run one phase across every checked week, sequentially so we don't hammer the
// API and so a single failure doesn't abort the rest. Weeks that aren't ready
// for the phase are skipped (and reported), not errored.
const BULK = {
  ingest: { path: "/api/ingest", label: "Ingest", ready: (w) => w.pdfs.length > 0,  need: "no PDFs" },
  quiz:   { path: "/api/quiz",   label: "Quiz",   ready: (w) => w.tiers.length > 0, need: "not ingested" },
  review: { path: "/api/review", label: "Review", ready: (w) => w.has_essay,        need: "no essay" },
};

function selectedWeeks() {
  return [...document.querySelectorAll(".week-cb:checked")].map((c) => parseInt(c.value, 10));
}

async function bulkRun(action, btn) {
  const cfg = BULK[action];
  const picked = selectedWeeks();
  if (!picked.length) { toast("Select at least one week first."); return; }
  const ready = picked.filter((wk) => cfg.ready(weekInfo(wk)));
  const skipped = picked.length - ready.length;
  if (!ready.length) { toast(`No selected week is ready to ${cfg.label} (${cfg.need}).`); return; }

  const failed = [];
  let done = 0;
  await withSpinner(btn, async () => {
    for (let i = 0; i < ready.length; i++) {
      const wk = ready[i];
      toast(`${cfg.label} Week ${String(wk).padStart(2, "0")}… (${i + 1}/${ready.length})`);
      try { await api(cfg.path, jsonBody({ week: wk })); done++; }
      catch (e) { failed.push(`W${wk}: ${e.message}`); }
    }
  });
  await refresh();

  let msg = `${cfg.label}: ${done}/${ready.length} done`;
  if (skipped) msg += ` · ${skipped} skipped (${cfg.need})`;
  if (failed.length) msg += ` · ${failed.length} failed`;
  toast(msg);
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
    await renderMarkdown($("#viewer-body"), md);
    rewriteAssetImages($("#viewer-body"), week);   // point relative img src at the asset route
  } catch (e) { $("#viewer-body").textContent = "Could not load file."; }
}

// Diagrams.md embeds images as `assets/NAME`; map those to the asset endpoint.
function rewriteAssetImages(container, week) {
  container.querySelectorAll("img").forEach((img) => {
    const src = img.getAttribute("src") || "";
    if (/^(https?:)?\/\//.test(src) || src.startsWith("/")) return;  // leave remote/absolute
    const file = src.replace(/^\.?\//, "").replace(/^assets\//, "");
    img.src = `/api/week/${week}/asset/${encodeURIComponent(file)}`;
  });
}

async function openDiagnostic() {
  showView("viewer");
  $("#viewer-title").textContent = "state/Diagnostic.md";
  const md = await (await fetch("/api/diagnostic")).text();
  renderMarkdown($("#viewer-body"), md);
}

// ---------------------------------------------------------------------- quiz
let quizWeek = null;
let quizSpec = null;                       // parsed Quiz.json for the open week
const weekInfo = (week) => state.weeks.find((w) => w.week === week) || {};

const TIER_ORDER = ["Beginner", "Intermediate", "Interleaved", "Advanced"];
const TIER_LABEL = {
  Beginner: "Beginner (기초)", Intermediate: "Intermediate (중급)",
  Interleaved: "Interleaved Review (이전 주 복습)", Advanced: "Advanced Essay Prompts (심화 논술)",
};
const isObjective = (t) => t === "mcq" || t === "cloze";

async function fetchFile(week, name) {
  const r = await fetch(`/api/week/${week}/file/${name}`);
  return r.ok ? r.text() : "";
}

async function openQuiz(week) {
  showView("quiz");
  quizWeek = week;
  quizSpec = null;
  $("#quiz-header").innerHTML = `📝 <strong>Week ${String(week).padStart(2, "0")} Quiz</strong>`;
  const w = weekInfo(week);
  if (!w.has_quiz) {
    $("#quiz-empty").classList.remove("hidden");
    $("#quiz-body").classList.add("hidden");
    return;
  }
  $("#quiz-empty").classList.add("hidden");
  $("#quiz-body").classList.remove("hidden");

  const rawJson = await fetchFile(week, "Quiz.json");
  if (rawJson) { try { quizSpec = JSON.parse(rawJson); } catch (_) { quizSpec = null; } }

  const list = $("#quiz-list"); list.innerHTML = "";
  if (quizSpec && Array.isArray(quizSpec.questions)) {
    renderQuizInteractive(quizSpec.questions);
  } else {
    // Legacy week (Quiz.md only, no structured answers): show static markdown.
    const art = el("article", "markdown"); list.appendChild(art);
    renderMarkdown(art, await fetchFile(week, "Quiz.md"));
    $("#quiz-score").textContent = "Legacy quiz — regenerate for the interactive checker.";
  }

  $("#quiz-essay").value = w.has_essay ? await fetchFile(week, "Essay.md") : "";
  if (w.has_feedback) renderMarkdown($("#quiz-feedback"), await fetchFile(week, "Feedback.md"));
  else $("#quiz-feedback").innerHTML = "";
}

function renderQuizInteractive(questions) {
  const list = $("#quiz-list"); list.innerHTML = "";
  TIER_ORDER.forEach((tier) => {
    const group = questions.filter((q) => q.tier === tier);
    if (!group.length) return;
    list.appendChild(el("h3", "qz-h", TIER_LABEL[tier] || tier));
    group.forEach((q, i) => list.appendChild(renderCard(q, i + 1)));
  });
  updateScore();
}

function renderCard(q, n) {
  const card = el("div", "q-card");
  card._q = q;

  const head = el("div", "q-head");
  head.appendChild(el("span", "q-id", q.id || `#${n}`));
  const badge = el("span", "q-badge"); badge.dataset.role = "badge";
  head.appendChild(badge);
  card.appendChild(head);
  card.appendChild(el("div", "q-prompt", q.prompt || ""));

  const body = el("div", "q-body");
  if (q.type === "mcq") {
    (q.options || []).forEach((opt) => {
      const lbl = el("label", "q-opt");
      const radio = el("input"); radio.type = "radio"; radio.name = q.id; radio.value = opt;
      lbl.appendChild(radio); lbl.appendChild(el("span", null, opt));
      body.appendChild(lbl);
    });
  } else if (q.type === "cloze" || q.type === "short") {
    const inp = el("input", "q-input"); inp.type = "text"; inp.placeholder = "Your answer (내 답)…";
    if (q.type === "cloze") inp.addEventListener("keydown", (e) => { if (e.key === "Enter") checkCard(card); });
    body.appendChild(inp);
  } else if (q.type === "essay") {
    body.appendChild(el("div", "q-essay-note", "Write your essay in the box below, then use Review on this week."));
  }
  card.appendChild(body);

  if (q.type !== "essay") {
    const acts = el("div", "q-acts");
    const objective = isObjective(q.type);
    const btn = el("button", "mini", objective ? "Check" : "Reveal answer");
    btn.onclick = () => (objective ? checkCard(card) : revealCard(card));
    acts.appendChild(btn);
    card.appendChild(acts);
  }
  const rev = el("div", "q-reveal hidden"); rev.dataset.role = "reveal";
  card.appendChild(rev);
  return card;
}

// --- checking -------------------------------------------------------------
function normalize(s) {
  return (s || "").toString().toLowerCase().trim()
    .replace(/\s+/g, " ")
    .replace(/^[\s"'(.,;:!?-]+|[\s"').,;:!?-]+$/g, "");
}
function mcqLetter(s) {
  const m = normalize(s).match(/^([a-z])\b/);
  return m ? m[1] : normalize(s);
}
function isCorrect(q, value) {
  if (q.type === "mcq") return mcqLetter(value) === mcqLetter(q.answer);
  if (q.type === "cloze") return (q.answers || []).map(normalize).includes(normalize(value));
  return null;
}
function cardValue(card) {
  const q = card._q;
  if (q.type === "mcq") {
    const sel = card.querySelector(`input[name="${q.id}"]:checked`);
    return sel ? sel.value : "";
  }
  const inp = card.querySelector(".q-input");
  return inp ? inp.value : "";
}

function checkCard(card, quiet) {
  const q = card._q;
  const value = cardValue(card);
  if (!value) { if (!quiet) toast("Select or type an answer first."); return; }
  const ok = isCorrect(q, value);
  const badge = card.querySelector('[data-role="badge"]');
  badge.textContent = ok ? "✓" : "✗";
  badge.className = "q-badge " + (ok ? "ok" : "bad");
  card.classList.toggle("answered-ok", !!ok);
  card.classList.toggle("answered-bad", !ok);
  card.dataset.checked = "1";
  revealCard(card);
  updateScore();
}

function revealCard(card) {
  const q = card._q;
  const rev = card.querySelector('[data-role="reveal"]');
  rev.innerHTML = "";
  const ans = q.type === "cloze" ? (q.answers || []).join("  /  ") : (q.answer || "");
  if (ans) {
    const a = el("div", "q-ans");
    a.appendChild(el("strong", null, "Answer (정답): "));
    a.appendChild(el("span", null, ans));
    rev.appendChild(a);
  }
  if (q.explanation) rev.appendChild(el("div", "q-exp", q.explanation));
  rev.classList.remove("hidden");
  card.dataset.revealed = "1";
}

function updateScore() {
  const cards = [...$("#quiz-list").querySelectorAll(".q-card")];
  const objective = cards.filter((c) => isObjective(c._q.type));
  if (!objective.length) { $("#quiz-score").textContent = ""; return; }
  const correct = objective.filter((c) => c.classList.contains("answered-ok")).length;
  const checked = objective.filter((c) => c.dataset.checked === "1").length;
  let txt = `Objective: ${correct} / ${objective.length} correct`;
  if (checked < objective.length) txt += ` · ${checked} checked`;
  $("#quiz-score").textContent = txt;
}

function assembleAnswers() {
  const lines = [`# Week ${quizWeek} — My Answers`, ""];
  TIER_ORDER.forEach((tier) => {
    const cards = [...$("#quiz-list").querySelectorAll(".q-card")]
      .filter((c) => c._q.tier === tier && c._q.type !== "essay");
    if (!cards.length) return;
    lines.push(`## ${TIER_LABEL[tier] || tier}`);
    cards.forEach((c) => lines.push(`- ${c._q.id}: ${cardValue(c).replace(/\s+/g, " ").trim()}`));
    lines.push("");
  });
  return lines.join("\n");
}

async function saveQuizFile(name, content, btn) {
  const fn = () => api("/api/save", jsonBody({ week: quizWeek, name, content }));
  return btn ? withSpinner(btn, fn) : fn();
}

$("#quiz-generate").onclick = async (e) => {
  toast(`Generating Week ${quizWeek} quiz… (gpt-oss, may take a minute)`);
  try {
    await withSpinner(e.target, () => api("/api/quiz", jsonBody({ week: quizWeek })));
    await refresh(); openQuiz(quizWeek); toast("Quiz ready.");
  } catch (err) { toast("Quiz failed: " + err.message); }
};

$("#quiz-checkall").onclick = () => {
  [...$("#quiz-list").querySelectorAll(".q-card")]
    .filter((c) => isObjective(c._q.type)).forEach((c) => checkCard(c, true));
  updateScore();
};

$("#quiz-reset").onclick = () => { if (quizSpec) { renderQuizInteractive(quizSpec.questions); $("#quiz-feedback").innerHTML = ""; } };

$("#quiz-essay-save").onclick = async (e) => {
  try {
    await saveQuizFile("Essay.md", $("#quiz-essay").value, e.target);
    await refresh(); toast("Essay saved — Review is now available on this week.");
  } catch (err) { toast("Save failed: " + err.message); }
};

$("#quiz-grade").onclick = async (e) => {
  if (!quizSpec) { toast("Generate the interactive quiz first."); return; }
  try {
    await saveQuizFile("Answers.md", assembleAnswers(), null);
    toast(`Submitting Week ${quizWeek} for feedback…`);
    const r = await withSpinner(e.target, () => api("/api/grade", jsonBody({ week: quizWeek })));
    renderMarkdown($("#quiz-feedback"), r.feedback);
    await refresh();
    toast(`Feedback ready · ${r.findings.length} finding(s) logged.`);
  } catch (err) { toast("Grading failed: " + err.message); }
};

// --------------------------------------------------------------------- chat
// Two live interlocutors share one chat panel: the Feynman pupil (teach-back) and
// Socrates (debate your essay against its critique).
const SESSIONS = {
  feynman: {
    path: "feynman", reply: "pupil", bubble: "pupil",
    header: (w) => `🧒 Feynman Pupil · Week ${String(w).padStart(2, "0")} — teach until it clicks. /done to end.`,
    connecting: "Connecting to the pupil…", placeholder: "Teach the pupil… (/done to end)",
  },
  socrates: {
    path: "socrates", reply: "socrates", bubble: "socrates",
    header: (w) => `🏛️ Socratic Debate · Week ${String(w).padStart(2, "0")} — defend your essay. /done to end.`,
    connecting: "Reading your essay & critique…", placeholder: "Defend your reasoning… (/done to end)",
  },
};

function startSession(week, kind) {
  const cfg = SESSIONS[kind];
  showView("chat");
  chatWeek = week;
  $("#chat-header").textContent = cfg.header(week);
  $("#chat-input").placeholder = cfg.placeholder;
  $("#chat-log").innerHTML = "";
  if (ws) { try { ws.close(); } catch (_) {} }
  ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/${cfg.path}/${week}`);
  setChatEnabled(false);
  addBubble("sys", cfg.connecting);

  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.role === cfg.reply) { addBubble(cfg.bubble, m.text); setChatEnabled(true); }
    else if (m.role === "sys") { addBubble("sys", m.text); }
    else if (m.role === "summary") { addBubble("sys", "Session summary saved to Diagnostic.md."); setChatEnabled(false); refresh(); }
    else if (m.role === "error") { addBubble("err", m.text); setChatEnabled(false); }
  };
  ws.onclose = () => setChatEnabled(false);
  ws.onerror = () => addBubble("err", "Connection error. Is the server running?");
}

const startChat = (week) => startSession(week, "feynman");
const startDebate = (week) => startSession(week, "socrates");

// Delete a whole week and its contents (notes, quiz, essay, PDFs). Irreversible.
async function deleteWeek(w, wkLabel) {
  const wkName = w.title || wkLabel;
  if (!confirm(`Delete ${wkName} and ALL its contents (notes, quiz, essay, PDFs)? This cannot be undone.`)) return;
  try {
    await api("/api/week/delete", jsonBody({ week: w.week }));
    toast(`${wkName} deleted.`);
    await refresh();
  } catch (e) { toast("Delete failed: " + e.message); }
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
$("#subject-select").onchange = (e) => { if (e.target.value) selectSubject(e.target.value); };
$("#subject-new").onclick = newSubject;
$("#subject-rename").onclick = renameSubject;
$("#subject-delete").onclick = deleteSubject;
$("#inbox-assign").onclick = assignSelected;
$("#inbox-all").onchange = (e) => {
  document.querySelectorAll(".inbox-cb").forEach((cb) => { cb.checked = e.target.checked; });
};
$("#weeks-all").onchange = (e) => {
  document.querySelectorAll(".week-cb").forEach((cb) => { cb.checked = e.target.checked; });
};
$("#bulk-ingest").onclick = (e) => bulkRun("ingest", e.currentTarget);
$("#bulk-quiz").onclick = (e) => bulkRun("quiz", e.currentTarget);
$("#bulk-review").onclick = (e) => bulkRun("review", e.currentTarget);
wireUpload();
refresh();
