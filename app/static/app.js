/* TReatyIQ UI — vanilla JS single-page app over the TReatyIQ API. No build step.
 *
 * Routes:
 *   #/                       treaty list + upload & extract
 *   #/treaty/{id}            treaty detail (versions / current values / audit)
 *   #/treaty/{id}/version/{n}  version review (data points, diff, approve/amend)
 */
"use strict";

const view = document.getElementById("view");
const actorInput = document.getElementById("actor");
actorInput.value = localStorage.getItem("rein_actor") || "reviewer";
actorInput.addEventListener("change", () => localStorage.setItem("rein_actor", actorInput.value));
const actor = () => actorInput.value.trim() || "reviewer";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function fmtValue(v) {
  if (v === null || v === undefined) return '<span class="value empty">— not set —</span>';
  const text = typeof v === "string" ? v : JSON.stringify(v);
  return `<span class="value">${esc(text)}</span>`;
}

function toast(msg, isError = false) {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.className = "show" + (isError ? " error" : "");
  setTimeout(() => (el.className = ""), isError ? 6000 : 2600);
}

async function api(path, opts = {}) {
  const resp = await fetch(path, opts);
  let body = null;
  try { body = await resp.json(); } catch { /* no body */ }
  if (!resp.ok) {
    const detail = body && body.detail ? (typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail)) : resp.statusText;
    throw new Error(detail);
  }
  return body;
}

const post = (path, payload) =>
  api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
const patch = (path, payload) =>
  api(path, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });

// Animated loader for long operations. `stages` is a list of messages shown
// in sequence (advancing on a timer) alongside a spinner and elapsed seconds.
// Returns a handle with setMessage() and stop().
function startLoader(container, stages, { block = false, stepMs = 5000 } = {}) {
  container.innerHTML =
    `<span class="loader${block ? " block" : ""}">
       <span class="spinner"></span>
       <span class="loader-msg"></span>
       <span class="loader-time"></span>
     </span>`;
  const msgEl = container.querySelector(".loader-msg");
  const timeEl = container.querySelector(".loader-time");
  const t0 = Date.now();
  let idx = 0;
  msgEl.textContent = stages[0] || "Working…";
  const tick = setInterval(() => {
    timeEl.textContent = `${Math.floor((Date.now() - t0) / 1000)}s`;
  }, 250);
  const advance = setInterval(() => {
    if (idx < stages.length - 1) msgEl.textContent = stages[++idx];
  }, stepMs);
  return {
    setMessage(m) { msgEl.textContent = m; },
    stop() { clearInterval(tick); clearInterval(advance); container.innerHTML = ""; },
  };
}

function chip(status) {
  return `<span class="chip ${esc(status)}">${esc(status.replace(/_/g, " "))}</span>`;
}

function confBar(c) {
  if (c === null || c === undefined) return "";
  const pct = Math.round(c * 100);
  const cls = c >= 0.9 ? "high" : c >= 0.7 ? "mid" : "low";
  return `<span class="conf ${cls}" title="confidence ${pct}%">
    <span class="bar"><span style="width:${pct}%"></span></span>
    <span class="small">${pct}%</span></span>`;
}

// Parse a user-typed value: JSON where possible (numbers, lists, booleans),
// plain string otherwise, empty -> null.
function parseValue(text) {
  const t = text.trim();
  if (t === "") return null;
  try { return JSON.parse(t); } catch { return t; }
}
function valueToInput(v) {
  if (v === null || v === undefined) return "";
  return typeof v === "string" ? v : JSON.stringify(v);
}

function normText(v) {
  return String(v ?? "").toLowerCase();
}

function formatDate(value) {
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "";
  const dd = String(d.getDate()).padStart(2, "0");
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const yyyy = d.getFullYear();
  return `${dd}/${mm}/${yyyy}`;
}

function formatDateTime(value) {
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "";
  const date = formatDate(d);
  const hh = String(d.getHours()).padStart(2, "0");
  const min = String(d.getMinutes()).padStart(2, "0");
  return `${date} ${hh}:${min}`;
}

function formatDateInput(value) {
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "";
  const dd = String(d.getDate()).padStart(2, "0");
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const yyyy = d.getFullYear();
  return `${yyyy}-${mm}-${dd}`;
}

// Editor control for a data-point value: a single-line input for short values,
// a multi-line textarea for long ones (lists, clauses, schedules). Both carry
// the `edit-value` class so callers read `.value` uniformly. `extraAttrs` lets
// callers add e.g. data-original for change tracking.
function valueEditorHtml(value, extraAttrs = "") {
  const v = valueToInput(value);
  const long = v.length > 45 || v.includes("\n");
  if (long) {
    const rows = Math.min(8, Math.max(3, Math.ceil(v.length / 60)));
    return `<textarea class="edit-value" rows="${rows}" ${extraAttrs}>${esc(v)}</textarea>`;
  }
  return `<input type="text" class="edit-value" value="${esc(v)}" ${extraAttrs} />`;
}

// ---------------------------------------------------------------------------
// Router
// ---------------------------------------------------------------------------

async function route() {
  const hash = location.hash || "#/";
  try {
    let m;
    if ((m = hash.match(/^#\/treaty\/([^/]+)\/version\/(\d+)$/))) {
      await renderVersion(m[1], parseInt(m[2], 10));
    } else if ((m = hash.match(/^#\/treaty\/([^/]+)$/))) {
      await renderTreaty(m[1]);
    } else if ((m = hash.match(/^#\/kb(?:\/(\w+))?$/))) {
      await renderKnowledgeBase(m[1] || "insights");
    } else {
      await renderHome();
    }
  } catch (err) {
    view.innerHTML = `<div class="banner error">${esc(err.message)}</div>`;
  }
  wrapTables();
  syncNav();
  window.scrollTo(0, 0);
}
window.addEventListener("hashchange", route);

// Highlight the active top-level menu item for the current route.
function syncNav() {
  const kb = (location.hash || "").startsWith("#/kb");
  document.querySelectorAll("header .nav a").forEach((a) => {
    a.classList.toggle("active", a.dataset.section === (kb ? "kb" : "review"));
  });
}

// ---------------------------------------------------------------------------
// Knowledge Base: portfolio analytics + bulk ingestion
// ---------------------------------------------------------------------------

const money = new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 });

// Horizontal bar chart from a list of {value, count}.
function barChart(buckets) {
  if (!buckets.length) return '<p class="muted small">No data yet.</p>';
  const max = Math.max(...buckets.map((b) => b.count));
  return `<div class="bars">${buckets.map((b) => `
    <div class="bar-row">
      <span class="bar-label" title="${esc(b.value)}">${esc(b.value)}</span>
      <span class="bar-track"><span class="bar-fill" style="width:${max ? (b.count / max) * 100 : 0}%"></span></span>
      <span class="bar-count">${b.count}</span>
    </div>`).join("")}</div>`;
}

async function renderKnowledgeBase(tab) {
  const tabs = ["insights", "ingest", "ask"];
  if (!tabs.includes(tab)) tab = "insights";
  view.innerHTML = `
    <div class="section-header">
      <h2>Knowledge Base</h2>
      <p class="muted small">Ingest many treaties into a shared corpus, then explore it. Analytics are
      computed directly from the extracted data (exact, never guessed); Ask uses semantic search over the
      corpus and answers with citations to the source treaties.</p>
    </div>
    <div class="tabs">
      <button data-kbtab="insights">Insights</button>
      <button data-kbtab="ingest">Ingest treaties</button>
      <button data-kbtab="ask">Ask</button>
    </div>
    <div id="kb-content"></div>`;

  const buttons = [...document.querySelectorAll(".tabs button[data-kbtab]")];
  buttons.forEach((b) => b.classList.toggle("active", b.dataset.kbtab === tab));
  buttons.forEach((b) => {
    b.onclick = () => { location.hash = `#/kb/${b.dataset.kbtab}`; };
  });

  const content = document.getElementById("kb-content");
  if (tab === "ingest") return renderKbIngest(content);
  if (tab === "ask") return renderKbAsk(content);
  return renderKbInsights(content);
}

async function renderKbAsk(content) {
  content.innerHTML = '<div class="panel"><div class="loader block"><span class="spinner"></span><span class="loader-msg">Checking index…</span></div></div>';
  const status = await api("/kb/status");

  content.innerHTML = `
    <div class="panel">
      <div class="row" style="justify-content:space-between">
        <div>
          <h2 style="margin:0 0 4px">Ask the corpus</h2>
          <p class="muted small" id="kb-index-status" style="margin:0"></p>
        </div>
        <button class="secondary" id="kb-reindex-btn">${status.ready ? "Refresh index" : "Build index"}</button>
      </div>
      <div class="row" style="margin-top:14px; align-items:flex-start">
        <textarea id="kb-question" rows="2" placeholder="e.g. Which treaties exclude cyber? What's the highest limit in EUR?"
          style="flex:1 1 420px"></textarea>
        <button id="kb-ask-btn" ${status.ready ? "" : "disabled"}>Ask</button>
      </div>
      <div id="kb-answers"></div>
    </div>`;

  const statusEl = document.getElementById("kb-index-status");
  const reindexBtn = document.getElementById("kb-reindex-btn");
  const askBtn = document.getElementById("kb-ask-btn");
  const questionEl = document.getElementById("kb-question");
  const answers = document.getElementById("kb-answers");

  const showStatus = (s) => {
    statusEl.textContent = s.ready
      ? `${s.indexed_chunks} of ${s.total_treaties} treaties indexed · ${s.embedding_model}`
      : `Not indexed yet — build the index to enable questions (${s.total_treaties} treaties available).`;
  };
  showStatus(status);

  reindexBtn.onclick = async () => {
    reindexBtn.disabled = true;
    const prev = reindexBtn.textContent;
    reindexBtn.textContent = "Indexing…";
    try {
      const r = await post("/kb/reindex", {});
      const s = await api("/kb/status");
      showStatus(s);
      askBtn.disabled = !s.ready;
      toast(`Indexed ${r.indexed_chunks} treaties`);
    } catch (err) {
      toast(err.message, true);
    } finally {
      reindexBtn.disabled = false;
      reindexBtn.textContent = prev === "Build index" ? "Refresh index" : prev;
    }
  };

  async function ask() {
    const q = questionEl.value.trim();
    if (!q) return;
    askBtn.disabled = true;
    const card = document.createElement("div");
    card.className = "kb-qa";
    card.innerHTML = `<div class="kb-q">${esc(q)}</div><div class="kb-a"></div>`;
    answers.prepend(card);
    const aEl = card.querySelector(".kb-a");
    const loader = startLoader(aEl, ["Searching the corpus…", "Reading the most relevant treaties…", "Composing the answer…"]);
    try {
      const body = await post("/kb/ask", { question: q });
      loader.stop();
      const sources = body.sources.length
        ? `<div class="kb-sources"><span class="chat-cite-label">Sources</span>${body.sources.map((s) =>
            `<a class="cite" href="#/treaty/${s.treaty_id}" title="${esc(s.name)}">${esc(s.reference)}</a>`).join("")}</div>`
        : "";
      aEl.innerHTML = simpleMarkdown(body.answer) + sources;
    } catch (err) {
      loader.stop();
      aEl.innerHTML = `<div class="banner error">${esc(err.message)}</div>`;
    } finally {
      askBtn.disabled = false;
    }
  }
  askBtn.onclick = ask;
  questionEl.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(); }
  });
}

async function renderKbInsights(content) {
  content.innerHTML = '<div class="panel"><div class="loader block"><span class="spinner"></span><span class="loader-msg">Computing analytics…</span></div></div>';
  const a = await api("/analytics/portfolio");
  if (a.total_treaties === 0) {
    content.innerHTML = `<div class="panel"><div class="empty-state">
      <div class="empty-icon" aria-hidden="true">📊</div>
      <h3>Nothing to analyse yet</h3>
      <p class="muted">Ingest some treaties to see portfolio breakdowns and totals.</p>
      <button onclick="location.hash='#/kb/ingest'">Ingest treaties</button>
    </div></div>`;
    return;
  }

  const kpis = `<div class="kpis">
    ${kpiTile(a.total_treaties, "Treaties in corpus", { cls: "accent", icon: "📚" })}
    ${kpiTile(a.by_currency.length, "Currencies", { icon: "💱" })}
    ${kpiTile((a.breakdowns.find((b) => b.key === "treaty_type")?.buckets.length) || 0, "Treaty types", { icon: "🏷️" })}
  </div>`;

  const charts = a.breakdowns.map((b) => `
    <div class="panel">
      <h2>Treaties by ${esc(b.label)}</h2>
      ${barChart(b.buckets)}
    </div>`).join("");

  const currencyRows = a.by_currency.map((r) => `
    <tr>
      <td class="mono">${esc(r.currency)}</td>
      <td>${r.count}</td>
      <td>${money.format(r.layer_limit_amount)}</td>
      <td>${money.format(r.maximum_cedant_retention_amount)}</td>
    </tr>`).join("");

  content.innerHTML = `
    ${kpis}
    <div class="panel" id="kb-summary-panel">
      <div class="row" style="justify-content:space-between">
        <h2 style="margin:0">Executive summary</h2>
        <button class="secondary" id="kb-summary-btn">Generate summary</button>
      </div>
      <div id="kb-summary" class="kb-summary muted small">
        Generate a narrative summary of the portfolio. The text is written by the assistant but grounded in the
        exact figures above — it can't invent numbers.
      </div>
    </div>
    <div class="kb-charts">${charts}</div>
    <div class="panel">
      <h2>Totals by currency</h2>
      <p class="muted small">Amounts are summed within each currency (cross-currency sums are not meaningful).</p>
      <table>
        <thead><tr><th>Currency</th><th>Treaties</th><th>Layer limit</th><th>Max cedant retention</th></tr></thead>
        <tbody>${currencyRows}</tbody>
      </table>
    </div>`;

  const summaryBtn = document.getElementById("kb-summary-btn");
  const summaryEl = document.getElementById("kb-summary");
  summaryBtn.onclick = async () => {
    summaryBtn.disabled = true;
    const loader = startLoader(summaryEl, [
      "Reading the portfolio figures…",
      "Writing the executive summary…",
      "Almost there…",
    ]);
    try {
      const body = await post("/analytics/summary", {});
      loader.stop();
      summaryEl.classList.remove("muted", "small");
      summaryEl.innerHTML = simpleMarkdown(body.summary);
    } catch (err) {
      loader.stop();
      summaryEl.innerHTML = `<div class="banner error">${esc(err.message)}</div>`;
    } finally {
      summaryBtn.disabled = false;
    }
  };
}

// Minimal markdown for narrative text: escapes first, then bullets, paragraphs,
// **bold** and *italic*. (The chat widget has its own copy scoped to its closure.)
function simpleMarkdown(text) {
  const lines = esc(text).split("\n");
  const out = [];
  let inList = false;
  const closeList = () => { if (inList) { out.push("</ul>"); inList = false; } };
  const inline = (s) => s
    .replace(/\*\*([^*]+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*([^*\n]+?)\*/g, "<em>$1</em>");
  for (const line of lines) {
    const bullet = line.match(/^\s*[-*]\s+(.*)$/);
    if (bullet) {
      if (!inList) { out.push("<ul>"); inList = true; }
      out.push(`<li>${inline(bullet[1])}</li>`);
    } else if (line.trim() === "") {
      closeList();
    } else {
      closeList();
      out.push(`<p>${inline(line)}</p>`);
    }
  }
  closeList();
  return out.join("");
}

function renderKbIngest(content) {
  content.innerHTML = `
    <div class="panel">
      <h2>Ingest treaties in bulk</h2>
      <p class="muted small">Select multiple treaty files (PDF, DOCX or TXT). Each is parsed, added to the
      knowledge base and indexed for Ask. Files are processed one at a time; you can watch progress below.</p>
      <div class="row">
        <label class="file-input">
          <input type="file" id="kb-files" accept=".pdf,.docx,.txt,.md" multiple />
          <span class="file-btn">Choose files</span>
          <span class="file-name">No files chosen</span>
        </label>
        <button id="kb-ingest-btn">Ingest all</button>
      </div>
      <div id="kb-progress" class="kb-progress"></div>
    </div>
    <div class="panel">
      <h2>Uploaded documents</h2>
      <div id="kb-docs"><div class="loader"><span class="spinner"></span><span class="loader-msg">Loading…</span></div></div>
    </div>`;

  const filesEl = document.getElementById("kb-files");
  const btn = document.getElementById("kb-ingest-btn");
  const progress = document.getElementById("kb-progress");

  async function loadDocs() {
    const docsEl = document.getElementById("kb-docs");
    const docs = await api("/documents");
    if (!docs.length) {
      docsEl.innerHTML = '<p class="muted small">No documents uploaded yet.</p>';
      return;
    }
    const rows = docs.map((d) => `<tr>
      <td>${esc(d.filename)}</td>
      <td>${chip(d.kind)}</td>
      <td class="small muted">${formatDateTime(d.created_at)}</td>
      <td class="small">${(d.text_length / 1000).toFixed(1)}k chars</td>
      <td>${d.treaty_id
        ? `<a href="#/treaty/${d.treaty_id}">${esc(d.treaty_reference || "open")}</a>`
        : '<span class="muted">—</span>'}</td>
    </tr>`).join("");
    docsEl.innerHTML = `<table><thead><tr><th>File</th><th>Kind</th><th>Uploaded</th><th>Size</th><th>Treaty</th></tr></thead>
      <tbody>${rows}</tbody></table>`;
    wrapTables();
  }
  loadDocs();

  btn.onclick = async () => {
    const files = [...filesEl.files];
    if (!files.length) return toast("Choose one or more files first", true);
    btn.disabled = true;
    filesEl.disabled = true;
    let ok = 0;
    const items = files.map((f, i) =>
      `<div class="ingest-item" data-i="${i}"><span class="ingest-state">⏳</span> ${esc(f.name)} <span class="ingest-note muted small"></span></div>`);
    progress.innerHTML = items.join("");

    for (let i = 0; i < files.length; i++) {
      const row = progress.querySelector(`.ingest-item[data-i="${i}"]`);
      const state = row.querySelector(".ingest-state");
      const note = row.querySelector(".ingest-note");
      state.textContent = "⚙️";
      note.textContent = "parsing…";
      try {
        const fd = new FormData();
        fd.append("file", files[i]);
        fd.append("kind", "treaty");
        fd.append("actor", actor());
        const doc = await api("/documents", { method: "POST", body: fd });
        const version = await post("/extractions", { document_id: doc.id, actor: actor() });
        // Auto-index for Ask (best-effort — embeddings may be unavailable).
        let indexed = false;
        try { await post(`/kb/index/${version.treaty_id}`, {}); indexed = true; } catch { /* skip */ }
        state.textContent = "✅";
        const found = version.data_points.filter((p) => p.value !== null).length;
        note.innerHTML = `added — ${found} fields · ${indexed ? "indexed ✓" : "not indexed"} · `
          + `<a href="#/treaty/${version.treaty_id}/version/1">review</a>`;
        ok++;
      } catch (err) {
        state.textContent = "❌";
        note.textContent = err.message;
      }
    }
    btn.disabled = false;
    filesEl.disabled = false;
    toast(`Ingested ${ok}/${files.length} treaties`);
    loadDocs();
    if (ok) {
      progress.insertAdjacentHTML("beforeend",
        `<p style="margin-top:12px"><button onclick="location.hash='#/kb/insights'">View insights</button></p>`);
    }
  };
}

// Wrap any rendered table in a horizontally scrollable container so wide
// tables never break the page layout (e.g. on a projector at a demo).
function wrapTables() {
  view.querySelectorAll("table:not([data-wrapped])").forEach((table) => {
    table.setAttribute("data-wrapped", "1");
    const wrap = document.createElement("div");
    wrap.className = "table-wrap";
    table.parentNode.insertBefore(wrap, table);
    wrap.appendChild(table);
  });
}

// ---------------------------------------------------------------------------
// Home: treaty list + upload & extract
// ---------------------------------------------------------------------------

function kpiTile(value, label, { sub = "", cls = "", icon = "" } = {}) {
  return `<div class="kpi ${cls}">
    ${icon ? `<span class="kpi-icon" aria-hidden="true">${icon}</span>` : ""}
    <span class="kpi-value">${value}</span>
    <span class="kpi-label">${esc(label)}</span>
    ${sub ? `<span class="kpi-sub">${esc(sub)}</span>` : ""}
  </div>`;
}

async function renderHome() {
  // Stats, treaties and the KB index set in parallel; all best-effort.
  const [treaties, stats, indexed] = await Promise.all([
    api("/treaties"),
    api("/stats").catch(() => null),
    api("/kb/indexed").catch(() => ({ treaty_ids: [] })),
  ]);
  const indexedSet = new Set(indexed.treaty_ids || []);
  const rows = treaties.map((t) => {
    const latest = t.versions[t.versions.length - 1];
    const approved = [...t.versions].reverse().find((v) => v.status === "approved");
    const rowFlags = {
      in_force: !!approved,
      needs_review: !!(latest && latest.status === "draft"),
      no_versions: !latest,
    };
    const rowSearch = normText([
      t.reference,
      t.name,
      latest ? latest.status : "",
      approved ? `approved v${approved.version_number}` : "",
      latest ? `latest v${latest.version_number}` : "",
    ].join(" "));
    return `<tr class="clickable" data-search="${esc(rowSearch)}" data-create-date="${formatDateInput(t.created_at)}" data-in-force="${rowFlags.in_force ? "1" : "0"}" data-needs-review="${rowFlags.needs_review ? "1" : "0"}" data-no-versions="${rowFlags.no_versions ? "1" : "0"}" onclick="location.hash='#/treaty/${t.id}'">
      <td class="mono">${esc(t.reference)}</td>
      <td>${esc(t.name)}</td>
      <td>v${latest ? latest.version_number : "-"} ${latest ? chip(latest.status) : ""}</td>
      <td>${approved ? "v" + approved.version_number : '<span class="muted">none</span>'}</td>
      <td>${indexedSet.has(t.id)
        ? '<span class="chip approved" title="Indexed for Knowledge Base search">KB ✓</span>'
        : '<span class="chip not_found" title="Not yet indexed for Ask">—</span>'}</td>
      <td class="small muted">${formatDate(t.created_at)}</td>
    </tr>`;
  }).join("");

  const kpis = stats ? `<div class="kpis">
    ${kpiTile(stats.treaties, "Treaties", { cls: "accent", icon: "📄" })}
    ${kpiTile(stats.in_force, "In force", { sub: `${stats.approved_versions} approved version${stats.approved_versions === 1 ? "" : "s"}`, cls: "ok", icon: "✅" })}
    ${kpiTile(stats.awaiting_review, "Awaiting review", { sub: "draft versions", cls: stats.awaiting_review ? "warn" : "", icon: "⏳" })}
    ${kpiTile(stats.amendments, "Amendments", { icon: "✏️" })}
    ${kpiTile(stats.documents, "Documents", { icon: "🗂️" })}
  </div>` : "";

  view.innerHTML = `
    <div class="section-header">
      <h2>Treaties Overview</h2>
      <p class="muted small">Key metrics for your treaty portfolio — how many treaties are tracked, how many
      are currently in force, how many draft versions are awaiting review, plus the total amendments and
      source documents on file.</p>
    </div>
    ${kpis}
    <div class="section-header">
      <h2>Upload Treaties</h2>
      <p class="muted small">Add new treaty file(s) for automatic extraction. Each upload creates a
      <b>draft</b> version for you to review — nothing is used downstream until it's approved.</p>
    </div>
    <div class="upload-tiles">
      <div class="panel upload-tile">
        <h2>Single treaty upload</h2>
        <p class="muted small">Upload a treaty file (PDF, DOCX or TXT). The parser extracts every
        defined data point with its source quote and confidence, and creates a <b>draft</b> for your review —
        nothing is used downstream until you approve it.</p>
        <div class="row">
          <label class="file-input">
            <input type="file" id="treaty-file" accept=".pdf,.docx,.txt,.md" />
            <span class="file-btn">Choose file</span>
            <span class="file-name">No file chosen</span>
          </label>
          <button id="btn-extract">Upload &amp; extract</button>
          <button class="ghost" id="btn-sample" title="Extract a bundled sample treaty">Try a sample</button>
          <span class="muted small" id="extract-status"></span>
        </div>
      </div>
      <div class="panel upload-tile">
        <h2>Multiple treaties upload <span class="chip superseded">coming soon</span></h2>
        <p class="muted small">Upload several treaty files at once and extract them in a batch.
        Each document will still create its own draft for individual review.
        Support upload of treaties and amendments in one go, with automatic mapping of amendments to the correct treaty.
        </p>
        <div class="row">
          <label class="file-input disabled">
            <input type="file" id="treaty-files-multi" accept=".pdf,.docx,.txt,.md" multiple disabled />
            <span class="file-btn">Choose files</span>
            <span class="file-name">No files chosen</span>
          </label>
          <button id="btn-extract-multi" disabled>Upload &amp; extract</button>
        </div>
      </div>
    </div>
    <div class="section-header">
      <h2>Treaties</h2>
      <p class="muted small">All treaties uploaded so far, with their latest version, in-force version and
      creation date. Search or filter to find a specific treaty.</p>
    </div>
    <div class="panel">
      ${treaties.length ? `
        <div class="filters">
          <label>
            <span>Search</span>
            <input type="search" id="portfolio-search" placeholder="Reference, treaty name, status…" />
          </label>
          <label>
            <span>Create Date</span>
            <input type="date" id="filter-date" />
          </label>
          <div class="filter-checks">
            <label class="inline"><input type="checkbox" id="filter-in-force" /> In force</label>
            <label class="inline"><input type="checkbox" id="filter-needs-review" /> Needs review</label>
            <label class="inline"><input type="checkbox" id="filter-no-versions" /> No versions</label>
          </div>
        </div>
      ` : ""}
      ${treaties.length === 0
        ? `<div class="empty-state">
             <div class="empty-icon" aria-hidden="true">📄🔍</div>
             <h3>No treaties yet</h3>
             <p class="muted">Upload a treaty document above — or extract a bundled sample to see the full
             workflow in action.</p>
             <button id="btn-sample-empty">Try a sample treaty</button>
           </div>`
        : `<table><thead><tr><th>Reference</th><th>Name</th><th>Latest version</th><th>In force</th><th>KB</th><th>Created</th></tr></thead>
           <tbody id="portfolio-body">${rows}</tbody></table>`}
    </div>`;

  const portfolioSearch = document.getElementById("portfolio-search");
  const filterInForce = document.getElementById("filter-in-force");
  const filterNeedsReview = document.getElementById("filter-needs-review");
  const filterNoVersions = document.getElementById("filter-no-versions");
  const filterDate = document.getElementById("filter-date");
  const portfolioRows = [...document.querySelectorAll("#portfolio-body tr")];
  const portfolioDatasetKeys = {
    in_force: "inForce",
    needs_review: "needsReview",
    no_versions: "noVersions",
  };
  function applyPortfolioFilters() {
    if (!portfolioRows.length) return;
    const q = normText(portfolioSearch?.value || "");
    const dateFilter = filterDate?.value || "";
    const activeFlags = [];
    if (filterInForce?.checked) activeFlags.push("in_force");
    if (filterNeedsReview?.checked) activeFlags.push("needs_review");
    if (filterNoVersions?.checked) activeFlags.push("no_versions");
    portfolioRows.forEach((tr) => {
      const matchesText = !q || tr.dataset.search.includes(q);
      const matchesFlags = !activeFlags.length
        || activeFlags.some((flag) => tr.dataset[portfolioDatasetKeys[flag]] === "1");
      const matchesDate = !dateFilter || tr.dataset.createDate === dateFilter;
      tr.style.display = matchesText && matchesFlags && matchesDate ? "" : "none";
    });
  }
  [portfolioSearch, filterInForce, filterNeedsReview, filterNoVersions, filterDate].forEach((el) => {
    if (!el) return;
    el.addEventListener(el.type === "search" ? "input" : "change", applyPortfolioFilters);
  });
  applyPortfolioFilters();

  // Extract a document into a new treaty draft, driving the shared loader.
  // `getDoc` returns the created document (from an upload or the sample loader).
  async function extractInto(statusEl, disableEls, getDoc) {
    disableEls.forEach((el) => el && (el.disabled = true));
    const loader = startLoader(statusEl, [
      "Uploading the document…",
      "Reading and parsing the document…",
      "Sending the document to the model…",
      "Extracting data points…",
      "Mapping values, source quotes and confidence…",
      "Still working — large documents take longer…",
      "Almost there — finalizing the draft…",
    ]);
    try {
      const doc = await getDoc();
      loader.setMessage("Extracting data points…");
      await post("/extractions", { document_id: doc.id, actor: actor() });
      const treaties2 = await api("/treaties");
      const t = treaties2[treaties2.length - 1];
      loader.stop();
      toast("Extraction complete — review the draft");
      location.hash = `#/treaty/${t.id}/version/1`;
    } catch (err) {
      loader.stop();
      toast(err.message, true);
      disableEls.forEach((el) => el && (el.disabled = false));
    }
  }

  const btnExtract = document.getElementById("btn-extract");
  const btnSample = document.getElementById("btn-sample");
  const status = document.getElementById("extract-status");

  btnExtract.onclick = () => {
    const fileEl = document.getElementById("treaty-file");
    if (!fileEl.files.length) return toast("Choose a file first", true);
    extractInto(status, [btnExtract, btnSample], async () => {
      const fd = new FormData();
      fd.append("file", fileEl.files[0]);
      fd.append("kind", "treaty");
      fd.append("actor", actor());
      return api("/documents", { method: "POST", body: fd });
    });
  };

  // "Try a sample": load the bundled sample treaty server-side, then extract.
  function loadSample(statusEl, disableEls) {
    extractInto(statusEl, disableEls, async () => {
      const fd = new FormData();
      fd.append("kind", "treaty");
      fd.append("actor", actor());
      return api("/documents/sample", { method: "POST", body: fd });
    });
  }
  if (btnSample) btnSample.onclick = () => loadSample(status, [btnExtract, btnSample]);
  const btnSampleEmpty = document.getElementById("btn-sample-empty");
  if (btnSampleEmpty) btnSampleEmpty.onclick = () => loadSample(status, [btnSampleEmpty]);
}

// ---------------------------------------------------------------------------
// Treaty detail: versions / current values / audit + amendment actions
// ---------------------------------------------------------------------------

async function renderTreaty(treatyId, tab = "versions") {
  const t = await api(`/treaties/${treatyId}`);
  const approved = [...t.versions].reverse().find((v) => v.status === "approved");

  const versionRows = t.versions.map((v) => `
    <tr class="clickable" onclick="location.hash='#/treaty/${t.id}/version/${v.version_number}'">
      <td><b>v${v.version_number}</b></td>
      <td>${chip(v.status)}</td>
      <td>${esc(v.origin.replace(/_/g, " "))}</td>
      <td>${esc(v.change_summary || "—")}</td>
      <td>${esc(v.effective_date || "—")}</td>
      <td class="small muted">${esc(v.created_by)} · ${formatDateTime(v.created_at)}</td>
    </tr>`).join("");

  view.innerHTML = `
    <div class="crumbs"><a href="#/">Treaties</a> / ${esc(t.reference)}</div>
    <div class="panel">
      <h2>${esc(t.name)}</h2>
      <div class="row small muted">
        <span class="mono">${esc(t.reference)}</span>
        <span>· in force: ${approved ? `v${approved.version_number}` : "none (awaiting approval)"}</span>
      </div>
    </div>
    <div class="tabs">
      <button data-tab="versions">Versions</button>
      <button data-tab="current">Current values</button>
      <button data-tab="audit">Audit trail</button>
    </div>
    <div id="tab-content"></div>
    <div class="panel" id="amend-panel">
      <h2>Amend this treaty</h2>
      ${approved ? "" : '<div class="banner warn">Amendments become available once a version is approved.</div>'}
      <div class="row" style="align-items:flex-start; gap:32px;">
        <div>
          <h3>From an adjustment document</h3>
          <p class="muted small" style="max-width:340px">Upload an addendum / endorsement. The parser maps its
          changes onto the data points and creates a new draft version for review.</p>
          <div class="row">
            <label class="file-input ${approved ? "" : "disabled"}">
              <input type="file" id="amend-file" accept=".pdf,.docx,.txt,.md" ${approved ? "" : "disabled"} />
              <span class="file-btn">Choose file</span>
              <span class="file-name">No file chosen</span>
            </label>
            <button id="btn-amend-doc" ${approved ? "" : "disabled"}>Upload &amp; apply</button>
          </div>
          <span class="muted small" id="amend-status"></span>
        </div>
        <div>
          <h3>Manually</h3>
          <p class="muted small" style="max-width:340px">Open the approved version and use “Start manual
          amendment” to change data points directly (with a business reason).</p>
          ${approved ? `<button class="secondary" onclick="location.hash='#/treaty/${t.id}/version/${approved.version_number}'">Open v${approved.version_number}</button>` : ""}
        </div>
      </div>
    </div>`;

  const tabContent = document.getElementById("tab-content");
  const tabButtons = [...document.querySelectorAll(".tabs button")];
  async function showTab(name) {
    tabButtons.forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
    if (name === "versions") {
      tabContent.innerHTML = `<div class="panel"><table>
        <thead><tr><th>Version</th><th>Status</th><th>Origin</th><th>Change summary</th><th>Effective</th><th>Created</th></tr></thead>
        <tbody>${versionRows}</tbody></table>
        <p class="muted small">Click a version to review its data points.</p></div>`;
    } else if (name === "current") {
      try {
        const cur = await api(`/treaties/${treatyId}/current`);
        const rows = Object.entries(cur.values)
          .filter(([, v]) => v !== null)
          .map(([k, v]) => `<tr><td class="mono">${esc(k)}</td><td>${fmtValue(v)}</td></tr>`).join("");
        tabContent.innerHTML = `<div class="panel">
          <div class="banner ok">Serving approved version v${cur.version_number} — these are the values downstream calculations receive.</div>
          <table><thead><tr><th>Field</th><th>Value</th></tr></thead><tbody>${rows}</tbody></table></div>`;
      } catch (err) {
        tabContent.innerHTML = `<div class="panel"><div class="banner warn">${esc(err.message)}</div></div>`;
      }
    } else if (name === "audit") {
      const [entries, verify] = await Promise.all([
        api(`/treaties/${treatyId}/audit`), api("/audit/verify"),
      ]);
      const rows = entries.map((e) => `<tr>
        <td class="small muted">${formatDateTime(e.timestamp)}</td>
        <td>${esc(e.actor)}</td>
        <td class="mono">${esc(e.action)}</td>
        <td class="small">${e.details ? esc(JSON.stringify(e.details)).slice(0, 160) : ""}</td>
        <td class="audit-hash mono">${esc(e.entry_hash.slice(0, 12))}…</td>
      </tr>`).join("");
      tabContent.innerHTML = `<div class="panel">
        <div class="banner ${verify.valid ? "ok" : "error"}">
          Audit chain ${verify.valid ? "verified — no tampering detected" : "BROKEN at entry " + verify.first_broken_entry_id}
          (${verify.entries_checked} entries checked)</div>
        <table><thead><tr><th>When</th><th>Actor</th><th>Action</th><th>Details</th><th>Hash</th></tr></thead>
        <tbody>${rows}</tbody></table></div>`;
    }
  }
  tabButtons.forEach((b) => (b.onclick = () => showTab(b.dataset.tab)));
  await showTab(tab);

  const amendBtn = document.getElementById("btn-amend-doc");
  if (amendBtn) amendBtn.onclick = async () => {
    const fileEl = document.getElementById("amend-file");
    const status = document.getElementById("amend-status");
    if (!fileEl.files.length) return toast("Choose an amendment document first", true);
    amendBtn.disabled = true;
    const loader = startLoader(status, [
      `Uploading “${fileEl.files[0].name}”…`,
      "Reading and parsing the amendment…",
      "Comparing against the current data points…",
      "Identifying which values change…",
      "Still working — large documents take longer…",
      "Almost there — preparing the draft…",
    ]);
    try {
      const fd = new FormData();
      fd.append("file", fileEl.files[0]);
      fd.append("kind", "amendment");
      fd.append("actor", actor());
      const doc = await api("/documents", { method: "POST", body: fd });
      loader.setMessage("Mapping changes onto data points…");
      const version = await post(`/treaties/${treatyId}/amendments/from-document`,
        { document_id: doc.id, actor: actor() });
      loader.stop();
      toast("Amendment parsed — review the new draft");
      location.hash = `#/treaty/${treatyId}/version/${version.version_number}`;
    } catch (err) {
      loader.stop();
      toast(err.message, true);
      amendBtn.disabled = false;
    }
  };
}

// ---------------------------------------------------------------------------
// Version review
// ---------------------------------------------------------------------------

// Render the product / benefit / cession-rule child collections as tables.
// Read-only in this MVP (edited via re-extraction / wholesale amendment).
function childCell(v) {
  if (v === null || v === undefined || v === "") return '<span class="muted">—</span>';
  return esc(String(v));
}
function childTable(title, icon, rows, cols) {
  const count = rows.length;
  const inner = count === 0
    ? '<p class="muted small">None recorded.</p>'
    : `<table><thead><tr>${cols.map((c) => `<th>${esc(c.label)}</th>`).join("")}</tr></thead>
       <tbody>${rows.map((r) => `<tr>${cols.map((c) => `<td>${childCell(r[c.key])}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
  return `<div class="panel">
    <h2>${icon} ${esc(title)} <span class="muted small">(${count})</span></h2>
    ${inner}
  </div>`;
}
function childSections(v) {
  return (
    childTable("Products", "📦", v.products || [], [
      { key: "product_code", label: "Code" },
      { key: "product_name", label: "Name" },
      { key: "product_type", label: "Type" },
      { key: "product_scope_status", label: "Scope" },
    ]) +
    childTable("Benefits", "🎯", v.benefits || [], [
      { key: "benefit_code", label: "Code" },
      { key: "benefit_name", label: "Name" },
      { key: "benefit_type", label: "Type" },
    ]) +
    childTable("Cession rules / layers", "📚", v.cession_rules || [], [
      { key: "layer_number", label: "Layer" },
      { key: "layer_name", label: "Name" },
      { key: "cession_basis", label: "Basis" },
      { key: "reinsurer_cession_ratio", label: "Cession %" },
      { key: "cedant_retention_ratio", label: "Retention %" },
      { key: "layer_limit_amount", label: "Layer limit" },
      { key: "maximum_cedant_retention_amount", label: "Max retention" },
      { key: "aggregation_basis", label: "Aggregation" },
      { key: "country_code", label: "Country" },
    ])
  );
}

async function renderVersion(treatyId, versionNumber) {
  const [t, v, diff] = await Promise.all([
    api(`/treaties/${treatyId}`),
    api(`/treaties/${treatyId}/versions/${versionNumber}`),
    api(`/treaties/${treatyId}/versions/${versionNumber}/diff`),
  ]);
  const isDraft = v.status === "draft";
  const changedKeys = new Set(diff.changes.map((c) => c.field_key));
  const oldValues = Object.fromEntries(diff.changes.map((c) => [c.field_key, c.old_value]));
  // Manual-amendment mode state (used when viewing an approved version)
  const pendingChanges = {};

  function pointRow(p) {
    const editable = isDraft;
    const changed = changedKeys.has(p.field_key) && diff.from_version !== null;
    const rowSearch = normText([
      p.field_label,
      p.field_key,
      p.status,
      p.value,
      p.source_quote,
      p.source_location,
      p.rationale,
      changed ? "changed" : "",
    ].join(" "));
    const valueCell = changed
      ? `<span class="diff-old">${esc(valueToInput(oldValues[p.field_key]) || "—")}</span>
         <span class="diff-new">${esc(valueToInput(p.value) || "—")}</span>`
      : fmtValue(p.value);
    return `<tr data-key="${esc(p.field_key)}" data-search="${esc(rowSearch)}" data-status="${esc(p.status)}" data-found="${p.value === null ? "0" : "1"}" data-changed="${changed ? "1" : "0"}" class="${p.value === null ? "notfound" : "found"}">
      <td style="min-width:170px"><b>${esc(p.field_label)}</b><br /><span class="mono muted small">${esc(p.field_key)}</span></td>
      <td style="min-width:220px">
        <div class="val-display">${valueCell}</div>
        ${editable ? `<div class="editbox" hidden>
            ${valueEditorHtml(p.value)}
            <input type="text" class="edit-note" placeholder="reason for change (optional)" />
            <button class="secondary btn-save">Save</button>
            <button class="ghost btn-cancel">Cancel</button>
          </div>` : ""}
      </td>
      <td>${chip(p.status)}</td>
      <td>${confBar(p.confidence)}</td>
      <td style="max-width:360px">
        ${p.source_location ? `<div class="loc">${esc(p.source_location)}</div>` : ""}
        ${p.source_quote ? `<div class="quote">“${esc(p.source_quote)}”</div>` : ""}
        ${p.rationale ? `<div class="small muted">${esc(p.rationale)}</div>` : ""}
      </td>
      <td>${editable ? '<button class="ghost btn-edit">Edit</button>' : ""}</td>
    </tr>`;
  }

  const diffBanner = diff.from_version !== null && diff.changes.length
    ? `<div class="banner warn"><b>${diff.changes.length} change(s)</b> vs approved v${diff.from_version}
       — changed values are shown as <span class="diff-old">old</span> → <span class="diff-new">new</span>.</div>`
    : "";

  view.innerHTML = `
    <div class="crumbs"><a href="#/">Treaties</a> / <a href="#/treaty/${t.id}">${esc(t.reference)}</a> / v${v.version_number}</div>
    <div class="panel">
      <div class="row" style="justify-content:space-between">
        <h2 style="margin:0">Version ${v.version_number} ${chip(v.status)}</h2>
        <div class="row" id="review-actions"></div>
      </div>
      <dl class="kv" style="margin-top:12px">
        <dt>Origin</dt><dd>${esc(v.origin.replace(/_/g, " "))}</dd>
        ${v.change_summary ? `<dt>Change summary</dt><dd>${esc(v.change_summary)}</dd>` : ""}
        ${v.effective_date ? `<dt>Effective date</dt><dd>${esc(v.effective_date)}</dd>` : ""}
        <dt>Created</dt><dd>${esc(v.created_by)} · ${formatDateTime(v.created_at)}</dd>
        ${v.reviewed_by ? `<dt>Reviewed</dt><dd>${esc(v.reviewed_by)} · ${formatDateTime(v.reviewed_at)}${v.review_note ? " — " + esc(v.review_note) : ""}</dd>` : ""}
      </dl>
    </div>
    ${v.source_document_id ? `<div class="panel">
      <div class="row" style="justify-content:space-between">
        <h2 style="margin:0">Source document</h2>
        <div class="row">
          <button class="secondary" id="btn-toggle-doc">Show document</button>
          <a class="ghost" href="/documents/${v.source_document_id}/file" target="_blank" rel="noopener">Open in new tab ↗</a>
        </div>
      </div>
      <div id="doc-viewer" hidden style="margin-top:12px"></div>
    </div>` : ""}
    ${isDraft ? `<div class="banner warn">This is a <b>draft</b>. Verify each data point against its source quote,
      correct anything wrong, then approve or reject. Values are not used downstream until approved.</div>` : ""}
    ${diffBanner}
    <div class="panel">
      <div class="row" style="justify-content:space-between">
        <h2 style="margin:0">Data points</h2>
        <label class="small muted"><input type="checkbox" id="hide-empty" checked /> hide fields not in document</label>
      </div>
      <div class="filters" style="margin-top:10px">
        <label>
          <span>Search</span>
          <input type="search" id="dp-search" placeholder="Field, key, value, source…" />
        </label>
        <label>
          <span>Status</span>
          <select id="dp-status">
            <option value="all">All</option>
            <option value="extracted">Extracted</option>
            <option value="edited">Edited</option>
            <option value="amended_by_document">Amended by document</option>
            <option value="carried_forward">Carried forward</option>
            <option value="not_found">Not in document</option>
            <option value="changed">Changed vs prior</option>
          </select>
        </label>
      </div>
      <table style="margin-top:10px">
        <thead><tr><th>Field</th><th>Value</th><th>Status</th><th>Confidence</th><th>Source / rationale</th><th></th></tr></thead>
        <tbody id="dp-body">${v.data_points.map(pointRow).join("")}</tbody>
      </table>
    </div>
    ${childSections(v)}`;

  // Hide-empty toggle
  const hideEmpty = document.getElementById("hide-empty");
  const dpSearch = document.getElementById("dp-search");
  const dpStatus = document.getElementById("dp-status");
  const rows = [...document.querySelectorAll("#dp-body tr")];
  function applyFilter() {
    if (!rows.length) return;
    const q = normText(dpSearch?.value || "");
    const status = dpStatus?.value || "all";
    rows.forEach((tr) => {
      const editing = !!tr.querySelector(".editbox:not([hidden])");
      const matchesText = !q || tr.dataset.search.includes(q);
      const matchesStatus =
        status === "all" ||
        tr.dataset.status === status ||
        (status === "changed" && tr.dataset.changed === "1");
      const hiddenByEmpty = hideEmpty.checked && tr.dataset.found === "0" && !editing;
      tr.style.display = matchesText && matchesStatus && !hiddenByEmpty ? "" : "none";
    });
  }
  hideEmpty.onchange = applyFilter;
  if (dpSearch) dpSearch.addEventListener("input", applyFilter);
  if (dpStatus) dpStatus.addEventListener("change", applyFilter);
  applyFilter();

  // Source-document viewer (lazy-loads the file on first Show)
  const docToggle = document.getElementById("btn-toggle-doc");
  if (docToggle) {
    const viewer = document.getElementById("doc-viewer");
    const fileUrl = `/documents/${v.source_document_id}/file`;
    docToggle.onclick = async () => {
      const showing = !viewer.hidden;
      if (showing) {
        viewer.hidden = true;
        docToggle.textContent = "Show document";
        return;
      }
      if (!viewer.dataset.loaded) {
        // Verify the file exists before embedding, to show a clean message.
        const head = await fetch(fileUrl, { method: "GET", headers: { Range: "bytes=0-0" } });
        if (!head.ok) {
          let msg = "The source file is not available.";
          try { msg = (await head.json()).detail || msg; } catch { /* keep default */ }
          viewer.innerHTML = `<div class="banner warn">${esc(msg)}</div>`;
        } else {
          viewer.innerHTML =
            `<iframe src="${fileUrl}" title="Source document" ` +
            `style="width:100%;height:640px;border:1px solid var(--border);border-radius:8px"></iframe>`;
        }
        viewer.dataset.loaded = "1";
      }
      viewer.hidden = false;
      docToggle.textContent = "Hide document";
    };
  }

  // Review actions
  const actions = document.getElementById("review-actions");
  if (isDraft) {
    actions.innerHTML = `
      <input type="text" id="review-note" placeholder="review note (optional)" style="width:220px" />
      <button id="btn-approve">Approve</button>
      <button class="danger" id="btn-reject">Reject</button>`;
    document.getElementById("btn-approve").onclick = () => review("approve");
    document.getElementById("btn-reject").onclick = () => review("reject");
  } else if (v.status === "approved") {
    actions.innerHTML = `<button class="secondary" id="btn-manual">Start manual amendment</button>`;
    document.getElementById("btn-manual").onclick = startManualAmendment;
  }

  async function review(kind) {
    const note = document.getElementById("review-note").value || null;
    try {
      await post(`/treaties/${treatyId}/versions/${versionNumber}/${kind}`, { actor: actor(), note });
      toast(kind === "approve" ? "Version approved — values now in force" : "Version rejected");
      location.hash = `#/treaty/${treatyId}`;
    } catch (err) { toast(err.message, true); }
  }

  // Inline editing (drafts). The change reason is captured in an inline
  // field — no native prompt(), which some browsers/extensions block.
  function openEditor(tr) {
    tr.querySelector(".val-display").hidden = true;
    tr.querySelector(".editbox").hidden = false;
    const editBtn = tr.querySelector(".btn-edit");
    if (editBtn) editBtn.hidden = true;
    tr.querySelector(".edit-value").focus();
  }
  function closeEditor(tr) {
    tr.querySelector(".val-display").hidden = false;
    tr.querySelector(".editbox").hidden = true;
    const editBtn = tr.querySelector(".btn-edit");
    if (editBtn) editBtn.hidden = false;
  }
  async function saveEditor(tr) {
    const key = tr.dataset.key;
    const value = parseValue(tr.querySelector(".edit-value").value);
    const note = tr.querySelector(".edit-note").value.trim() || null;
    try {
      await patch(`/treaties/${treatyId}/versions/${versionNumber}/data-points/${key}`,
        { value, note, actor: actor() });
      toast(`Updated ${tr.querySelector("b").textContent}`);
      await renderVersion(treatyId, versionNumber);
    } catch (err) { toast(err.message, true); }
  }

  document.querySelectorAll("#dp-body .btn-edit").forEach((btn) => {
    btn.onclick = () => openEditor(btn.closest("tr"));
  });
  document.querySelectorAll("#dp-body .btn-save").forEach((btn) => {
    btn.onclick = () => saveEditor(btn.closest("tr"));
  });
  document.querySelectorAll("#dp-body .btn-cancel").forEach((btn) => {
    btn.onclick = () => closeEditor(btn.closest("tr"));
  });
  // Enter saves, Escape cancels while editing.
  document.querySelectorAll("#dp-body .editbox").forEach((box) => {
    box.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); saveEditor(box.closest("tr")); }
      else if (e.key === "Escape") { e.preventDefault(); closeEditor(box.closest("tr")); }
    });
  });

  // Manual amendment mode (approved versions): edit values -> collect ->
  // submit as one amendment with a reason.
  function startManualAmendment() {
    document.querySelectorAll("#dp-body tr").forEach((tr) => {
      const key = tr.dataset.key;
      const current = v.data_points.find((p) => p.field_key === key);
      const cell = tr.children[1];
      cell.innerHTML = `<div class="editbox">
        ${valueEditorHtml(current.value, `data-original="${esc(valueToInput(current.value))}"`)}
      </div>`;
    });
    actions.innerHTML = `
      <input type="text" id="amend-reason" placeholder="business reason (required)" style="width:240px" />
      <label class="small muted" style="display:inline-flex;align-items:center;gap:6px">
        effective date <input type="date" id="amend-effective" />
      </label>
      <button id="btn-submit-amend">Create amendment draft</button>
      <button class="secondary" id="btn-cancel-amend">Cancel</button>`;
    document.getElementById("btn-cancel-amend").onclick = () => renderVersion(treatyId, versionNumber);
    document.getElementById("btn-submit-amend").onclick = async () => {
      const reason = document.getElementById("amend-reason").value.trim();
      if (!reason) return toast("A business reason is required", true);
      const changes = {};
      document.querySelectorAll("#dp-body .editbox .edit-value").forEach((inp) => {
        if (inp.value !== inp.dataset.original) {
          changes[inp.closest("tr").dataset.key] = parseValue(inp.value);
        }
      });
      if (!Object.keys(changes).length) return toast("No values were changed", true);
      try {
        const nv = await post(`/treaties/${treatyId}/amendments/manual`, {
          changes, reason,
          effective_date: document.getElementById("amend-effective").value.trim() || null,
          actor: actor(),
        });
        toast(`Draft v${nv.version_number} created with ${Object.keys(changes).length} change(s)`);
        location.hash = `#/treaty/${treatyId}/version/${nv.version_number}`;
      } catch (err) { toast(err.message, true); }
    };
  }
}

// Reflect the chosen file's name in our styled file pickers (delegated, so it
// works for pickers created on any re-render).
document.addEventListener("change", (e) => {
  const inp = e.target;
  if (inp && inp.matches && inp.matches('.file-input input[type="file"]')) {
    const nameEl = inp.parentElement.querySelector(".file-name");
    if (!nameEl) return;
    if (!inp.files.length) nameEl.textContent = inp.multiple ? "No files chosen" : "No file chosen";
    else if (inp.multiple && inp.files.length > 1) nameEl.textContent = `${inp.files.length} files chosen`;
    else nameEl.textContent = inp.files[0].name;
  }
});

// ---------------------------------------------------------------------------
// Chat assistant (floating pop-up)
//
// Injected once into <body> so it survives SPA re-renders. On a treaty page it
// posts the treaty id so answers are grounded in that treaty's data; elsewhere
// it's a general reinsurance / how-to-use-the-app assistant. The model is
// called with no tools bound (server side), so it has no web access.
// ---------------------------------------------------------------------------

function initChat() {
  // The treaty currently open (if any), read live from the hash at send time.
  const treatyIdFromHash = () => {
    const m = (location.hash || "").match(/^#\/treaty\/([^/]+)/);
    return m ? m[1] : null;
  };

  const wrap = document.createElement("div");
  wrap.id = "chat";
  wrap.innerHTML = `
    <button id="chat-launch" title="Ask the treaty assistant" aria-label="Open assistant">
      <span class="chat-launch-icon">💬</span>
      <span class="chat-launch-text">Ask</span>
    </button>
    <section id="chat-panel" hidden aria-label="Treaty assistant">
      <header class="chat-head">
        <div class="chat-title">
          <b>TreatyIQ Assistant</b>
          <span id="chat-context" class="chat-context"></span>
        </div>
        <div class="chat-actions">
          <button id="chat-new" class="chat-icon-btn" title="New conversation" aria-label="New conversation"><span class="chat-new-icon" aria-hidden="true">✎</span></button>
          <button id="chat-close" class="chat-icon-btn" title="Close" aria-label="Close">×</button>
        </div>
      </header>
      <div id="chat-log" class="chat-log"></div>
      <form id="chat-form" class="chat-form">
        <textarea id="chat-input" rows="1" placeholder="Ask a question…"
          autocomplete="off"></textarea>
        <button type="submit" id="chat-send" title="Send">Send</button>
      </form>
    </section>`;
  document.body.appendChild(wrap);

  const panel = wrap.querySelector("#chat-panel");
  const launch = wrap.querySelector("#chat-launch");
  const log = wrap.querySelector("#chat-log");
  const form = wrap.querySelector("#chat-form");
  const input = wrap.querySelector("#chat-input");
  const sendBtn = wrap.querySelector("#chat-send");
  const contextEl = wrap.querySelector("#chat-context");

  // Conversation history sent to the API: [{role, content}, ...].
  const history = [];
  const MAX_HISTORY_MESSAGES = 8;
  let busy = false;

  // Inline markdown on already-escaped text: **bold**, *italic*, `code`.
  // Bold is resolved before italic so "**x**" doesn't leave stray asterisks.
  function renderInline(s) {
    return s
      .replace(/\*\*([^*]+?)\*\*/g, "<strong>$1</strong>")
      .replace(/\*([^*\n]+?)\*/g, "<em>$1</em>")
      .replace(/`([^`\n]+?)`/g, "<code>$1</code>");
  }

  // A minimal Markdown renderer for the assistant's replies: bullet lists
  // (- or * lines), paragraphs, and inline formatting. Escapes first, so no
  // model output can inject HTML.
  function renderText(text) {
    const lines = esc(text).split("\n");
    const out = [];
    let inList = false;
    const closeList = () => { if (inList) { out.push("</ul>"); inList = false; } };
    for (const line of lines) {
      const bullet = line.match(/^\s*[-*]\s+(.*)$/);
      if (bullet) {
        if (!inList) { out.push("<ul>"); inList = true; }
        out.push(`<li>${renderInline(bullet[1])}</li>`);
      } else if (line.trim() === "") {
        closeList();
        out.push('<span class="chat-gap"></span>');
      } else {
        closeList();
        out.push(`<div>${renderInline(line)}</div>`);
      }
    }
    closeList();
    return out.join("");
  }

  function addMessage(role, content, { typing = false, citations = [] } = {}) {
    const el = document.createElement("div");
    el.className = `chat-msg ${role}` + (typing ? " typing" : "");
    if (typing) {
      el.innerHTML = '<span class="chat-dots"><span></span><span></span><span></span></span>';
    } else {
      el.innerHTML = renderText(content);
      if (citations.length) {
        const cite = document.createElement("div");
        cite.className = "chat-cite";
        cite.innerHTML = '<span class="chat-cite-label">Sources</span>' +
          citations.map((c) => `<span class="cite">${esc(c)}</span>`).join("");
        el.appendChild(cite);
      }
    }
    log.appendChild(el);
    log.scrollTop = log.scrollHeight;
    return el;
  }

  // Reflect where the assistant is grounded, and greet on first open per context.
  function updateContext() {
    const onTreaty = !!treatyIdFromHash();
    contextEl.textContent = onTreaty ? "Grounded in this treaty" : "General assistant";
    contextEl.className = "chat-context" + (onTreaty ? " grounded" : "");
  }

  function greet() {
    if (log.childElementCount > 0) return;
    const onTreaty = !!treatyIdFromHash();
    addMessage("assistant", onTreaty
      ? "Hi! Ask me anything about this treaty — its terms, versions, or what changed in an amendment."
      : "Hi! Ask me about your portfolio — how many treaties you have, which are in force, which need review — or about reinsurance concepts and using TreatyIQ. Open a treaty to ask about its specific values.");
  }

  function openPanel() {
    panel.hidden = false;
    launch.classList.add("open");
    updateContext();
    greet();
    input.focus();
  }
  function closePanel() {
    panel.hidden = true;
    launch.classList.remove("open");
  }

  function newConversation() {
    history.length = 0;
    log.innerHTML = "";
    greet();
    input.focus();
  }

  function pushHistory(message) {
    history.push(message);
    if (history.length > MAX_HISTORY_MESSAGES) {
      history.splice(0, history.length - MAX_HISTORY_MESSAGES);
    }
  }

  launch.onclick = () => (panel.hidden ? openPanel() : closePanel());
  wrap.querySelector("#chat-close").onclick = closePanel;
  wrap.querySelector("#chat-new").onclick = newConversation;

  // Auto-grow the input up to a few lines.
  input.addEventListener("input", () => {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 120) + "px";
  });
  // Enter sends, Shift+Enter inserts a newline.
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      form.requestSubmit();
    }
  });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text || busy) return;
    busy = true;
    sendBtn.disabled = true;
    input.value = "";
    input.style.height = "auto";

    addMessage("user", text);
    pushHistory({ role: "user", content: text });
    const typing = addMessage("assistant", "", { typing: true });

    try {
      const body = await post("/chat", {
        messages: history,
        treaty_id: treatyIdFromHash(),
      });
      typing.remove();
      addMessage("assistant", body.reply, { citations: body.citations || [] });
      pushHistory({ role: "assistant", content: body.reply });
    } catch (err) {
      typing.remove();
      const el = addMessage("assistant", "Sorry — " + err.message);
      el.classList.add("error");
    } finally {
      busy = false;
      sendBtn.disabled = false;
      input.focus();
    }
  });

  // Keep the grounding label in sync as the user navigates the SPA.
  window.addEventListener("hashchange", () => {
    if (!panel.hidden) updateContext();
  });
}

initChat();

route();
