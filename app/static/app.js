/* ReIn UI — vanilla JS single-page app over the ReIn API. No build step.
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
    } else {
      await renderHome();
    }
  } catch (err) {
    view.innerHTML = `<div class="banner error">${esc(err.message)}</div>`;
  }
  window.scrollTo(0, 0);
}
window.addEventListener("hashchange", route);

// ---------------------------------------------------------------------------
// Home: treaty list + upload & extract
// ---------------------------------------------------------------------------

async function renderHome() {
  const treaties = await api("/treaties");
  const rows = treaties.map((t) => {
    const latest = t.versions[t.versions.length - 1];
    const approved = [...t.versions].reverse().find((v) => v.status === "approved");
    return `<tr class="clickable" onclick="location.hash='#/treaty/${t.id}'">
      <td class="mono">${esc(t.reference)}</td>
      <td>${esc(t.name)}</td>
      <td>v${latest ? latest.version_number : "-"} ${latest ? chip(latest.status) : ""}</td>
      <td>${approved ? "v" + approved.version_number : '<span class="muted">none</span>'}</td>
      <td class="small muted">${new Date(t.created_at).toLocaleDateString()}</td>
    </tr>`;
  }).join("");

  view.innerHTML = `
    <div class="panel">
      <h2>New treaty from document</h2>
      <p class="muted small">Upload a treaty wording (PDF, DOCX or TXT). The parser extracts every
      defined data point with its source quote and confidence, and creates a <b>draft</b> for your review —
      nothing is used downstream until you approve it.</p>
      <div class="row">
        <label class="file-input">
          <input type="file" id="treaty-file" accept=".pdf,.docx,.txt,.md" />
          <span class="file-btn">Choose file</span>
          <span class="file-name">No file chosen</span>
        </label>
        <button id="btn-extract">Upload &amp; extract</button>
        <span class="muted small" id="extract-status"></span>
      </div>
    </div>
    <div class="panel">
      <h2>Treaties</h2>
      ${treaties.length === 0
        ? '<p class="muted">No treaties yet — upload a document above to get started.</p>'
        : `<table><thead><tr><th>Reference</th><th>Name</th><th>Latest version</th><th>In force</th><th>Created</th></tr></thead>
           <tbody>${rows}</tbody></table>`}
    </div>`;

  document.getElementById("btn-extract").onclick = async () => {
    const fileEl = document.getElementById("treaty-file");
    const status = document.getElementById("extract-status");
    if (!fileEl.files.length) return toast("Choose a file first", true);
    const btn = document.getElementById("btn-extract");
    btn.disabled = true;
    const loader = startLoader(status, [
      `Uploading “${fileEl.files[0].name}”…`,
      "Reading and parsing the document…",
      "Sending the document to the model…",
      "Extracting data points…",
      "Mapping values, source quotes and confidence…",
      "Still working — large documents take longer…",
      "Almost there — finalizing the draft…",
    ]);
    try {
      const fd = new FormData();
      fd.append("file", fileEl.files[0]);
      fd.append("kind", "treaty");
      fd.append("actor", actor());
      const doc = await api("/documents", { method: "POST", body: fd });
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
      btn.disabled = false;
    }
  };
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
      <td class="small muted">${esc(v.created_by)} · ${new Date(v.created_at).toLocaleString()}</td>
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
        <td class="small muted">${new Date(e.timestamp).toLocaleString()}</td>
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
    const valueCell = changed
      ? `<span class="diff-old">${esc(valueToInput(oldValues[p.field_key]) || "—")}</span>
         <span class="diff-new">${esc(valueToInput(p.value) || "—")}</span>`
      : fmtValue(p.value);
    return `<tr data-key="${esc(p.field_key)}" class="${p.value === null ? "notfound" : "found"}">
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
        <dt>Created</dt><dd>${esc(v.created_by)} · ${new Date(v.created_at).toLocaleString()}</dd>
        ${v.reviewed_by ? `<dt>Reviewed</dt><dd>${esc(v.reviewed_by)} · ${new Date(v.reviewed_at).toLocaleString()}${v.review_note ? " — " + esc(v.review_note) : ""}</dd>` : ""}
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
      <table style="margin-top:10px">
        <thead><tr><th>Field</th><th>Value</th><th>Status</th><th>Confidence</th><th>Source / rationale</th><th></th></tr></thead>
        <tbody id="dp-body">${v.data_points.map(pointRow).join("")}</tbody>
      </table>
    </div>`;

  // Hide-empty toggle
  const hideEmpty = document.getElementById("hide-empty");
  function applyFilter() {
    document.querySelectorAll("#dp-body tr.notfound").forEach((tr) => {
      tr.style.display = hideEmpty.checked && !tr.querySelector(".editbox:not([hidden])") ? "none" : "";
    });
  }
  hideEmpty.onchange = applyFilter;
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
    if (nameEl) nameEl.textContent = inp.files.length ? inp.files[0].name : "No file chosen";
  }
});

route();
