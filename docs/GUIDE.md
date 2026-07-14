# TreatyIQ — How the app is built, end to end

A complete walkthrough for someone who knows Python but is new to the front
end. By the end you'll understand every file, how the pieces talk to each
other, the architecture, and how you'd rebuild it yourself.

> Read it top to bottom the first time. After that, use it as a reference —
> each section is self-contained.

---

## Table of contents

1. [The 60-second mental model](#1-the-60-second-mental-model)
2. [The two halves and how they talk (REST/JSON)](#2-the-two-halves-and-how-they-talk-restjson)
3. [Architecture: the layered "onion"](#3-architecture-the-layered-onion)
4. [Folder & file map — what each file is for](#4-folder--file-map--what-each-file-is-for)
5. [One request, traced end to end](#5-one-request-traced-end-to-end)
6. [Backend deep dive (Python)](#6-backend-deep-dive-python)
7. [Frontend deep dive (from scratch)](#7-frontend-deep-dive-from-scratch)
8. [The domain design decisions that matter](#8-the-domain-design-decisions-that-matter)
9. [How to rebuild this from zero](#9-how-to-rebuild-this-from-zero)
10. [Glossary](#10-glossary)
11. [How to present it](#11-how-to-present-it)

---

## 1. The 60-second mental model

The app does one job: **turn a reinsurance treaty document into structured,
reviewable, versioned data.**

The flow a user experiences:

```
Upload PDF ─▶ AI extracts ~40 data points ─▶ Human reviews & corrects
   ─▶ Approves ─▶ Values are "in force" for downstream calculations
   ─▶ Later: amend (from a document or by hand) ─▶ new version ─▶ review again
Everything is logged in a tamper-evident audit trail.
```

Technically there are **two programs** running:

- **The backend** — a Python web server (FastAPI). It holds the data, talks to
  the AI model, enforces the rules, and exposes an **API** (a set of URLs that
  return JSON).
- **The frontend** — a web page (HTML + CSS + JavaScript) that runs in the
  browser. It calls the backend's API and draws the screens.

They are completely separate. The browser and the server only ever exchange
**text** (JSON) over HTTP. That separation is the single most important idea in
modern web apps — internalize it and everything else falls into place.

The app has since grown **two top-level areas** (a menu switches between them):

- **Treaty Review** — the core loop above: upload → extract → review → approve →
  amend, per treaty, human-in-the-loop and audited.
- **Knowledge Base** — works across the *whole book* of treaties: portfolio
  **analytics**, an AI **summary**, and semantic **Ask** (Q&A with citations).

Plus a floating **chat assistant** that can answer about the treaty you're
looking at, or the portfolio in general. Everything below still centres on the
review loop — it's the heart — but §8.7–8.9 cover these newer pieces.

---

## 2. The two halves and how they talk (REST/JSON)

### HTTP in one paragraph

The browser sends a **request**: a method + a URL (+ maybe a body). The server
sends back a **response**: a status code + a body. That's it.

- **Methods** describe intent: `GET` (read), `POST` (create/do), `PATCH`
  (modify), `DELETE` (remove).
- **Status codes** describe outcome: `200` OK, `201` Created, `404` Not Found,
  `409` Conflict, `422` Unprocessable (bad input), `500` Server error.
- **Body** is the payload. Here it's almost always **JSON** — a text format
  that looks exactly like a Python dict/list.

### What "the API" is

The backend exposes URLs like:

| You want to… | Method + URL |
|---|---|
| List treaties | `GET /treaties` |
| Upload a document | `POST /documents` · list them `GET /documents` |
| Run extraction | `POST /extractions` |
| Fix one data point | `PATCH /treaties/{id}/versions/1/data-points/reinsurer_cession_ratio` |
| Approve a version | `POST /treaties/{id}/versions/1/approve` |
| Dashboard numbers | `GET /stats` |
| The field catalogue (+ metadata) | `GET /catalog` · `GET /catalog/fields` |
| Portfolio analytics / summary | `GET /analytics/portfolio` · `POST /analytics/summary` |
| KB index: build / status / which | `POST /kb/reindex` · `GET /kb/status` · `GET /kb/indexed` |
| Ask the corpus (RAG) | `POST /kb/ask` |
| Chat assistant | `POST /chat` |

Each returns JSON. This style — nouns as URLs, verbs as HTTP methods — is
called **REST**. The frontend is just a program that calls these URLs and
renders the JSON.

### See it yourself

FastAPI auto-generates interactive docs. Run the app and open
`http://localhost:8000/docs` — you can click any endpoint, fill a form, and see
the exact request/response. This is the best way to *feel* the API.

---

## 3. Architecture: the layered "onion"

The backend is organized in **layers**, each only allowed to call the layer
below it. This is the key to keeping a codebase maintainable.

```
        ┌──────────────────────────────────────────────┐
        │  API layer          app/api/*.py             │   HTTP in/out, validation
        │  (routes)           "web plumbing"            │
        ├──────────────────────────────────────────────┤
        │  Service layer      app/services/*.py        │   business rules,
        │                     "the brain"              │   the actual logic
        ├──────────────────────────────────────────────┤
        │  Model layer        app/models.py            │   database tables as
        │  (ORM)                                        │   Python classes
        ├──────────────────────────────────────────────┤
        │  Database           SQLite / Postgres        │   where bytes live
        └──────────────────────────────────────────────┘

  Cross-cutting: app/schemas/*  (data shapes)   app/config.py (settings)
```

Why this matters:

- **Routes stay thin.** A route reads the request, calls one service function,
  returns the result. It contains no business logic.
- **Services are testable in isolation.** The rules ("only drafts can be
  edited", "approving supersedes the previous version") live in
  `app/services/treaties.py` and can be reasoned about without HTTP.
- **Models are the single source of truth for data shape.** Change a column in
  one place.

A useful phrase to say out loud: *"Routes handle the web, services handle the
rules, models handle the data."*

---

## 4. Folder & file map — what each file is for

```
ReIn/
├── app/                      ← the backend application (a Python package)
│   ├── main.py               ← creates the FastAPI app, wires routers, serves the UI, inits MLflow
│   ├── config.py             ← all settings (DB URL, chat/extraction/embeddings providers, keys, MLflow)
│   ├── database.py           ← DB engine + "give me a session" helper
│   ├── models.py             ← the database tables, as Python classes (ORM)
│   ├── observability.py      ← optional MLflow tracing/metrics (no-op when disabled)
│   │
│   ├── api/                  ← the HTTP layer (URL handlers = "routes")
│   │   ├── routes_documents.py   ← upload / list / fetch / view documents
│   │   ├── routes_treaties.py    ← extract, review, approve, amend, catalogue, stats, audit
│   │   ├── routes_analytics.py   ← portfolio analytics + AI summary (Knowledge Base)
│   │   ├── routes_kb.py          ← semantic index (build/status/indexed) + RAG "Ask"
│   │   └── routes_chat.py        ← the treaty-aware chat assistant
│   │
│   ├── services/             ← the business logic (no HTTP here)
│   │   ├── documents.py          ← turn an uploaded file into plain text
│   │   ├── llm.py                ← build the chat & extraction models (Anthropic/Ollama/Azure)
│   │   ├── embeddings.py         ← build the embeddings model (Ollama/Azure) for search
│   │   ├── extraction.py         ← ask the AI to fill the data-point schema
│   │   ├── treaties.py           ← versioning, review, amendments (the core)
│   │   ├── audit.py              ← the hash-chained audit trail
│   │   ├── stats.py              ← dashboard KPI counts
│   │   ├── analytics.py          ← deterministic portfolio breakdowns (never the LLM)
│   │   ├── summary.py            ← LLM portfolio summary, grounded in the analytics
│   │   ├── chat.py               ← the assistant (grounded per-treaty / portfolio; no tools)
│   │   ├── rag.py                ← chunk, embed, retrieve, answer with citations
│   │   └── errors.py             ← turn AI/network failures into clean HTTP errors
│   │
│   ├── schemas/              ← data *shapes* (Pydantic models), not tables
│   │   ├── treaty_fields.py      ← THE data-point catalogue (metadata-driven)
│   │   └── api.py                ← request/response shapes for the API
│   │
│   └── static/               ← the frontend (served as-is to the browser)
│       ├── index.html            ← the single HTML page (header nav + view)
│       ├── style.css             ← all the styling
│       ├── app.js                ← the entire UI logic (routing + rendering + chat widget)
│       └── img/                  ← logo assets
│
├── tests/                    ← automated tests (pytest); a FAKE AI + a FAKE embedder, no keys
│   ├── conftest.py               ← shared setup + the fakes + isolated per-module DB
│   └── test_*.py                 ← one file per area
│
├── scripts/                  ← reset_db.py (wipe & recreate all tables) + diagnostics
├── samples/                  ← example treaty + amendment documents
├── supabase/schema.sql       ← the same tables, as SQL, for Postgres/Supabase
├── docs/GUIDE.md             ← this file
├── requirements.txt          ← Python dependencies
├── .env.example              ← template for your local secrets/config
└── README.md                 ← quickstart + API summary
```

The `__init__.py` files are empty — they just tell Python "this folder is a
package" so `from app.services import treaties` works.

### File-by-file, one line each

**Backend core**
- `main.py` — the entry point. Builds the app, includes the routers, mounts
  `/static`, serves `index.html` at `/`, and creates DB tables on startup.
- `config.py` — a `Settings` class (Pydantic). Reads environment variables and
  `.env`. One place for every knob.
- `database.py` — creates the SQLAlchemy **engine** (the DB connection factory)
  and `get_db()`, which hands each request its own **session** (a unit of work).
- `models.py` — six tables as classes: `Document`, `Treaty`, `TreatyVersion`,
  `DataPoint`, `TreatyChunk` (the semantic index), `AuditLog`. Also the
  status/origin constants.
- `observability.py` — optional MLflow helpers: `init_mlflow()`, a `run()`
  context manager, and `log_extraction()` / `log_reindex()`. Everything is a
  no-op unless `MLFLOW_ENABLED=true`, and MLflow is imported lazily so the app
  runs without it installed.

**API layer**
- `routes_documents.py` — `POST /documents` (upload), `GET /documents` (list),
  `/{id}`, `/text`, `/file` (view the original), `POST /documents/sample`.
- `routes_treaties.py` — the core loop: `/catalog`, `/catalog/fields`, `/stats`,
  `/extractions`, the treaty/version reads, `PATCH` a data point, approve/reject,
  the two amendment endpoints, `/current`, and the audit endpoints.
- `routes_analytics.py` — `GET /analytics/portfolio` (deterministic breakdowns)
  and `POST /analytics/summary` (the grounded AI summary).
- `routes_kb.py` — the semantic index: `POST /kb/reindex`, `GET /kb/status`,
  `GET /kb/indexed`, `POST /kb/index/{id}`, and `POST /kb/ask` (RAG).
- `routes_chat.py` — `POST /chat`, the treaty-aware assistant.

**Service layer**
- `documents.py` — `extract_text()` (PDF via pypdf, DOCX via docx2txt, TXT
  directly) and `sha256_hex()`.
- `llm.py` — `get_chat_model()` and `get_extraction_model()` return LangChain
  chat models for whichever provider each is set to (chat and extraction can use
  *different* providers). Lazy imports so you only install what you use.
- `embeddings.py` — `get_embeddings()` returns an `Embedder` (Ollama or Azure),
  tagged with a `model_id` so vectors from different models never mix.
- `extraction.py` — two functions that send the document text to the model and
  get back a validated Pydantic object (treaty extraction / amendment changes).
- `treaties.py` — the heart: create a treaty from an extraction, edit/approve/
  reject a draft, create amendment versions, diff versions. All the rules live
  here.
- `stats.py` — `compute_stats()`: the home-dashboard KPI counts (shared by the
  `/stats` route and the chat assistant's portfolio overview).
- `analytics.py` — `portfolio_analytics()`: counts per category + totals per
  currency, computed **in SQL/Python, never by the LLM** (see §8.7).
- `summary.py` — `summarize_portfolio()`: an LLM executive summary *fed the exact
  analytics numbers* so it can't invent figures.
- `chat.py` — `answer()`: the assistant. No tools are bound, so it has no web
  access; it's grounded in one treaty or the portfolio overview (see §8.8).
- `rag.py` — the Ask pipeline: `_chunk_text` → `reindex`/`index_treaty` (embed &
  store) → `retrieve` (cosine) → `answer_question` (grounded, with citations).
- `audit.py` — `record()` appends a hash-chained entry; `verify_chain()`
  re-walks it to detect tampering.
- `errors.py` — a context manager that maps AI/network exceptions to friendly
  HTTP errors instead of raw 500s.

**Schemas**
- `treaty_fields.py` — the **metadata-driven catalogue**: `_FIELDS` lists every
  data point with its category, requirement (mandatory/optional) and description;
  the `TreatyExtraction` Pydantic model is generated from it (`create_model`), and
  `field_metadata()` exposes the metadata. Change `_FIELDS` and the whole app
  follows (see §8.1).
- `api.py` — the request bodies and response shapes (`VersionDetail`,
  `StatsOut`, `PortfolioAnalytics`, `KbAnswer`, …). These define what the API
  accepts and returns.

**Frontend**
- `index.html` — a nearly empty shell with one `<div id="view">`.
- `style.css` — the look (colors, tiles, tables, inputs).
- `app.js` — the whole app: a tiny router + functions that fetch JSON and build
  HTML.

---

## 5. One request, traced end to end

Let's follow **"user clicks Approve on version 1."** This shows every layer.

1. **Browser (app.js).** The click handler runs:
   ```js
   await post(`/treaties/${treatyId}/versions/1/approve`, { actor, note });
   ```
   `post()` is a helper that does `fetch(url, {method:"POST", body: JSON...})`.

2. **Network.** An HTTP request leaves the browser:
   `POST /treaties/abc/versions/1/approve` with body `{"actor":"clem"}`.

3. **FastAPI routing (main → routes_treaties).** FastAPI matches the URL to the
   `approve_version` function in `routes_treaties.py`. It:
   - parses the JSON body into a `ReviewRequest` Pydantic object (auto-validated),
   - injects a database session via `Depends(get_db)`.

4. **Route calls the service.**
   ```python
   version = treaty_service.get_version(db, treaty_id, version_number)
   return _version_detail(treaty_service.approve_version(db, version, payload.actor, payload.note))
   ```
   The route has no rules — it delegates.

5. **Service enforces the rules (services/treaties.py).** `approve_version`:
   - refuses if the version isn't a draft (`_require_draft`),
   - finds the previously-approved version and marks it `superseded`,
   - sets this version to `approved`, stamps reviewer + timestamp,
   - calls `audit.record(...)` twice (supersede + approve),
   - `db.commit()` — writes it all in one transaction.

6. **Models + DB.** SQLAlchemy translates the Python object changes into SQL
   `UPDATE`/`INSERT` statements against SQLite/Postgres.

7. **Response goes back up.** The service returns the updated `TreatyVersion`
   object → the route converts it to a `VersionDetail` Pydantic model → FastAPI
   serializes that to JSON → HTTP `200` with the JSON body.

8. **Browser renders.** `app.js` gets the JSON, shows a toast ("Version
   approved"), and navigates to the treaty page, which re-fetches and redraws.

That round trip — **click → fetch → route → service → model → DB → JSON →
re-render** — is the whole app, repeated for every action.

---

## 6. Backend deep dive (Python)

You know Python, so this focuses on the four libraries and the patterns.

### 6.1 FastAPI — the web framework

FastAPI turns a Python function into an HTTP endpoint with a **decorator**:

```python
@router.get("/stats", response_model=StatsOut)
def get_stats(db: Session = Depends(get_db)) -> StatsOut:
    ...
```

- `@router.get("/stats")` — "call this function for `GET /stats`."
- `response_model=StatsOut` — FastAPI validates and documents the output shape.
- `db: Session = Depends(get_db)` — **dependency injection**: before running the
  function, FastAPI calls `get_db()` and passes the result in. This is how every
  route gets a fresh database session without creating one manually.

Path and body parameters are just function parameters:

```python
@router.post("/treaties/{treaty_id}/versions/{version_number}/approve")
def approve_version(treaty_id: str, version_number: int, payload: ReviewRequest, db=Depends(get_db)):
```
`treaty_id`/`version_number` come from the URL; `payload` (a Pydantic model)
comes from the JSON body. FastAPI reads the type hints and does the parsing and
validation for you. Wrong types → automatic `422` with a helpful message.

`app/main.py` assembles everything:
```python
app.include_router(documents_router)   # add the /documents endpoints
app.include_router(treaties_router)    # add the treaty endpoints
app.mount("/static", StaticFiles(directory=STATIC_DIR))  # serve css/js
@app.get("/") def ui(): return FileResponse(index.html)  # serve the page
```

### 6.2 Pydantic — data shapes & validation

A Pydantic model is a class where each attribute has a type. Pydantic enforces
the types at runtime and converts to/from JSON. Two distinct uses here:

- **API contracts** (`schemas/api.py`): e.g. `ReviewRequest` says a review body
  has `actor: str` and optional `note`. If the client sends garbage, FastAPI
  rejects it before your code runs.
- **The extraction schema** (`schemas/treaty_fields.py`): `TreatyExtraction`
  isn't just validation — its JSON-schema form is *handed to the AI* as the
  exact structure to fill. This is the clever bit (see §8.1).

`ExtractedField` is the reusable unit:
```python
class ExtractedField(BaseModel):
    value: FieldValue                 # the answer (string/number/list/None)
    source_quote: Optional[str]       # the exact text that proves it
    source_location: Optional[str]    # where in the document
    confidence: float                 # 0..1, the model's certainty
    rationale: Optional[str]          # one-line explanation
```
Every one of the ~40 fields is an `ExtractedField`, which is why the UI can show
a quote and a confidence bar next to every value.

### 6.3 SQLAlchemy — the ORM (tables as classes)

An **ORM** (Object-Relational Mapper) lets you work with rows as Python objects
instead of writing SQL. A model class = a table; an instance = a row.

```python
class Treaty(Base):
    __tablename__ = "treaties"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    reference: Mapped[str] = mapped_column(String(256), unique=True, index=True)
    versions: Mapped[list["TreatyVersion"]] = relationship(...)  # a treaty has many versions
```

- `relationship(...)` lets you write `treaty.versions` in Python and SQLAlchemy
  fetches the related rows.
- `ForeignKey("treaties.id")` on `TreatyVersion` links a version to its treaty.

The six tables and how they relate:
```
Document        (an uploaded file: text + original bytes + sha256)
Treaty  1───*  TreatyVersion  1───*  DataPoint
   │                │                    (one row per field per version, with provenance)
   │                └── source_document_id → Document
   └── 1───*  TreatyChunk   (the semantic index: one text chunk + embedding per treaty)
AuditLog        (append-only log; not linked by FK, keyed by treaty_id)
```

A **session** (`get_db()`) is a workspace: you add/modify objects, then
`db.commit()` flushes them as one transaction. If anything raises before commit,
nothing is written.

Two ways the code reads data:
```python
db.get(Treaty, treaty_id)                        # fetch by primary key
db.execute(select(Treaty).where(...)).scalars()  # a query
```

### 6.4 LangChain — the AI abstraction

LangChain gives every model provider the same interface, so the app isn't tied
to one vendor. `services/llm.py` builds the right one:

```python
def get_chat_model() -> BaseChatModel:
    provider = settings.llm_provider          # "anthropic" | "ollama" | "azure_openai"
    return _BUILDERS[provider](settings)      # returns a LangChain chat model
```

The magic method is `with_structured_output`:
```python
structured = llm.with_structured_output(TreatyExtraction)
result = structured.invoke(messages)     # result is a validated TreatyExtraction
```
LangChain converts your Pydantic class into a JSON schema, tells the model "you
must return data in exactly this shape," and parses the reply back into your
class. That's how free-form document text becomes a typed object.

### 6.5 The audit hash chain (a neat, presentable detail)

Each audit entry stores a SHA-256 hash computed over *the previous entry's hash*
plus its own content:

```
entry₁.hash = sha256( GENESIS + entry₁.content )
entry₂.hash = sha256( entry₁.hash + entry₂.content )
entry₃.hash = sha256( entry₂.hash + entry₃.content )
```

Change any past entry and its hash no longer matches, and every later hash
breaks too. `verify_chain()` recomputes the whole chain to detect tampering.
This is the same idea a blockchain uses, in ~40 lines (`services/audit.py`).

---

## 7. Frontend deep dive (from scratch)

This is the part you asked about most, so we start from the very beginning.

### 7.1 The three languages of the web

A web page is always three things, with clean separation of concerns:

- **HTML** = the *structure/content* (boxes, text, inputs). Nouns.
- **CSS** = the *appearance* (colors, spacing, layout). Adjectives.
- **JavaScript** = the *behavior* (respond to clicks, fetch data, change the
  page). Verbs.

The browser downloads all three, builds an in-memory tree of the HTML called the
**DOM** (Document Object Model), paints it using the CSS, and runs the JS.

### 7.2 The DOM — the page as a tree you can edit

Every HTML tag becomes a **node** in a tree. JavaScript can read and change that
tree *live*, and the browser instantly repaints. Core operations:

```js
document.getElementById("view")     // find a node by its id
element.innerHTML = "<p>Hi</p>"     // replace a node's contents with HTML
element.addEventListener("click", fn) // run fn when clicked
element.textContent = "5"           // set text safely (no HTML)
```

**This app's entire strategy:** keep one empty container in the HTML and, in
JavaScript, set its `innerHTML` to a freshly-built string of HTML whenever the
screen changes. That's what a "single-page app" (SPA) is — one HTML file, many
screens drawn by JS. No page reloads.

### 7.3 `index.html` — the shell (22 lines)

```html
<body>
  <header> … app title, "signed in as" input … </header>
  <main id="view">Loading…</main>   <!-- everything is drawn into here -->
  <div id="toast"></div>            <!-- little popup messages -->
  <script src="/static/app.js"></script>
</body>
```

Notice there are no treaty tables or forms in the HTML — they don't exist until
`app.js` builds them. The whole app is `<div id="view">` + JavaScript.

### 7.4 `app.js` — the whole UI, explained by its parts

It's ~600 lines but only a handful of ideas. Read it in this order:

**(a) Small helpers (top of the file).**
```js
function esc(s) { … }      // escape text so it can't inject HTML (security)
async function api(path, opts) {           // fetch JSON, throw on error
  const resp = await fetch(path, opts);
  const body = await resp.json();
  if (!resp.ok) throw new Error(body.detail);
  return body;
}
const post = (path, payload) => api(path, {method:"POST", body: JSON.stringify(payload), headers:{...}});
```
`fetch` is the browser's built-in way to make HTTP calls — the frontend's
equivalent of Python's `requests`. `await` waits for the network without
freezing the page (asynchronous JavaScript).

**(b) The router.** The app fakes multiple "pages" using the URL **hash**
(the part after `#`, which never hits the server):
```js
async function route() {
  const hash = location.hash || "#/";
  if (matches "#/treaty/{id}/version/{n}")  await renderVersion(id, n);
  else if (matches "#/treaty/{id}")         await renderTreaty(id);
  else if (matches "#/kb/{tab}")            await renderKnowledgeBase(tab);
  else                                      await renderHome();
}
window.addEventListener("hashchange", route);  // re-run when the hash changes
route();                                        // and once on load
```
So `location.hash = "#/treaty/abc"` navigates — no server round trip, no reload.
This is a **client-side router**, the core trick of every SPA (React Router etc.
do exactly this, with more machinery).

**(c) The three `render*` functions.** Each one:
1. `await`s the data it needs from the API,
2. builds an HTML string with template literals (backtick strings with
   `${...}`),
3. sets `view.innerHTML = ...`,
4. attaches event handlers to the buttons it just created.

Example skeleton (`renderHome`):
```js
async function renderHome() {
  const [treaties, stats] = await Promise.all([api("/treaties"), api("/stats").catch(()=>null)]);
  view.innerHTML = `
    ${kpiTiles(stats)}
    <div class="panel"> … upload form … </div>
    <div class="panel"> … table of ${treaties.map(rowHtml).join("")} … </div>`;
  document.getElementById("btn-extract").onclick = async () => { … upload+extract … };
}
```
`Promise.all` runs two fetches at once. `.map(...).join("")` turns an array of
rows into one HTML string — the JS equivalent of a Jinja `{% for %}` loop.

**(d) Event handlers do the writes.** A handler gathers input values, calls
`post`/`patch`, shows a toast, and re-renders (often by changing
`location.hash`, which triggers the router). That's the full write path.

**Mental model for the whole frontend:** *fetch JSON → build an HTML string →
drop it into `#view` → wire up the buttons.* Every screen is that loop.

### 7.5 `style.css` — how the styling works

CSS is a list of rules: `selector { property: value; }`. A selector points at
DOM nodes; the block sets their appearance.

```css
.panel { background: #fff; border: 1px solid var(--border); border-radius: 10px; }
.chip.approved { background: var(--ok-soft); color: var(--ok); }
```
- `.panel` targets any element with `class="panel"`.
- `var(--border)` reads a **CSS variable** defined once at the top in `:root`
  (the app's color palette). Change one variable, restyle the whole app.
- **Flexbox/Grid** (`display:flex`, `display:grid`) handle layout — e.g. the KPI
  tiles use `grid-template-columns: repeat(auto-fit, minmax(150px,1fr))`, which
  means "fit as many ~150px columns as will fit, then stretch them." That's the
  responsive row of tiles, in one line.

The file is organized top-down: variables → base elements (buttons, inputs) →
components (panels, tables, chips, tiles, loader, file picker).

### 7.6 How the frontend and backend actually connect

They connect **only** through those `fetch` calls to the API URLs. There is no
shared code, no shared memory. If you opened the Network tab in the browser's
dev tools, you'd literally see `GET /treaties`, `POST /extractions`, etc. and
their JSON. That's the entire contract.

Because of that clean seam, you could throw away `app.js` and rebuild the
frontend in React/Vue/Svelte without touching the backend — or write a totally
different client (a script, a mobile app) against the same API.

---

## 8. The domain design decisions that matter

These are the "why," and they make the best talking points.

### 8.1 One catalogue drives extraction, validation, storage, and the UI

`schemas/treaty_fields.py` is the **single source of truth** for "what is a
treaty's data." It's **metadata-driven**: a list `_FIELDS` gives each data point
a `(key, requirement, category, description)`, where *requirement* is
Mandatory/Optional and *category* is one of Treaty / Product & Benefit /
Cession & Layers. From that one list:
- the `TreatyExtraction` Pydantic model is **generated** (`create_model`), which
  is the JSON schema LangChain forces the AI to fill,
- `/catalog` lists field → description; `/catalog/fields` returns the full
  metadata (category, mandatory, …),
- manual edits are validated against the field keys,
- each field becomes a `DataPoint` row,
- the UI renders a row per field.

Add an entry to `_FIELDS` and the entire pipeline picks it up. That's the payoff
of schema-driven design — say this in a presentation and people nod.

> The catalogue is currently **flat** (single product/benefit, layers 1–3 as
> columns). Modelling multiple products/benefits/layers per treaty as real
> one-to-many tables is a planned enhancement — see `docs/BACKLOG.md`.

### 8.2 Transparency: never store a bare value

Every extracted value carries its **source quote, location, confidence, and
rationale**. The reviewer can verify each number against the document before
approving. The app is explicitly *not* a black box — that's a deliberate,
demonstrable design goal, visible in the review screen.

### 8.3 Human-in-the-loop with immutable versions

- Extraction produces a **draft**. Only a human `approve` makes values usable
  downstream (`GET /current` refuses to serve anything but an approved version).
- Approved versions are **immutable** — editing one returns `409`. To change an
  approved treaty you create an **amendment**, which copies the latest approved
  version, applies changes, and starts a new draft. History is never rewritten.
- This is the state machine in `services/treaties.py`:
  `draft → approved → (superseded by next approved)`, or `draft → rejected`.

### 8.4 Auditability

Every state change is appended to a hash-chained log (§6.5). On Postgres a
trigger even blocks `UPDATE`/`DELETE` on the log at the database level. You can
prove the trail wasn't altered via `GET /audit/verify`.

### 8.5 Provider independence

`services/llm.py` isolates the AI vendor behind one function. Switching between
Claude, a local Ollama model, and Azure OpenAI is a config change, not a code
change. The rest of the app only knows "a chat model that can do structured
output."

### 8.6 Config over hard-coding

`config.py` reads everything from environment/`.env`: the database URL (so the
same code runs on SQLite locally and Supabase Postgres in production), the
chat/extraction/embeddings providers and keys, token limits, MLflow settings.
No secrets in code; no code changes to deploy.

### 8.7 The Knowledge Base — deterministic analytics vs. RAG

The KB works across the *whole book* of treaties (it's the same corpus as Treaty
Review — every treaty is in it automatically). It answers **two very different
kinds of question with two different mechanisms**, and keeping them separate is
the most important design decision here:

- **Quantitative / aggregate** ("how many treaties per type?", "total limit by
  currency?") → answered by **plain aggregation over the extracted fields**
  (`services/analytics.py`), *never* by the LLM. LLMs can't be trusted to count.
  The AI **summary** (`services/summary.py`) is even *fed* these computed numbers
  and told to use only them, so the prose can't invent figures.
- **Qualitative / semantic** ("which treaties are quota share?") → answered by
  **RAG** (`services/rag.py`): each treaty is rendered to a text chunk, embedded
  (`services/embeddings.py`), and stored in the `treaty_chunks` table; at question
  time the question is embedded, the closest chunks are retrieved by cosine
  similarity, and the chat model answers **using only those chunks**, citing the
  source treaties.

The vector store is JSON-in-a-column with in-Python cosine (works on SQLite and
Postgres; pgvector is the production swap). Each chunk is tagged with the
embedding `model_id`, so switching embedding models just means reindexing —
vectors from different models never mix. The index is built on demand
(`POST /kb/reindex`) and per-treaty on bulk ingest (`POST /kb/index/{id}`); the
home list shows a **KB** flag for which treaties are searchable.

### 8.8 The chat assistant — grounded, and deliberately tool-free

`services/chat.py` powers the floating assistant. Two guarantees:

- **No web access, by construction.** The model is called with `llm.invoke(...)`
  and **no tools bound**, so it physically cannot browse or take actions — it can
  only reason over the conversation and the context we hand it.
- **Grounded.** On a treaty page it's given that treaty's data; elsewhere it's
  given the portfolio overview (`services/stats.py`). Grounded answers cite the
  treaty fields they used, and those citations are **validated against the real
  field labels** so a hallucinated one is dropped.

The history is capped (recent turns + per-message length) so a long or pasted-in
conversation can't blow up cost/latency.

### 8.9 Observability (optional) — MLflow

`app/observability.py` adds MLflow tracing/metrics, entirely **opt-in**
(`MLFLOW_ENABLED`, default off) and imported lazily so the app runs without
MLflow installed. When on: `mlflow.langchain.autolog()` traces every LLM call;
extraction runs log field coverage/confidence; index builds log chunks/latency
by embedding model. It's *model/quality* observability — distinct from the
hash-chained audit trail (§8.4), which is the compliance record. See
`docs/BACKLOG.md` for planned refinements (batch runs, retrieval-quality eval).

---

## 9. How to rebuild this from zero

A milestone path you could actually follow. Each step is runnable before moving
on — that's the secret to not getting overwhelmed.

1. **Hello API.** `pip install fastapi uvicorn`. One file with
   `@app.get("/health")` returning `{"status":"ok"}`. Run
   `uvicorn main:app --reload`, open `/docs`. *You now have a web server.*

2. **A database.** `pip install sqlalchemy`. Define one `Treaty` model, a
   `get_db` dependency, `create_all` on startup. Add `POST /treaties` and
   `GET /treaties`. *You can now persist and read data.*

3. **The extraction schema.** Write `ExtractedField` + a small
   `TreatyExtraction` with 3–4 fields. Add `GET /catalog` that returns the field
   names. *You've defined your domain.*

4. **Call an LLM.** `pip install langchain-anthropic`. Write
   `get_chat_model()` and an `extract_treaty()` that does
   `llm.with_structured_output(TreatyExtraction).invoke(text)`. Add
   `POST /extractions` that takes raw text and returns the structured result.
   *The AI now fills your schema.*

5. **Documents.** Add file upload (`POST /documents`), parse PDF/DOCX/TXT to
   text, store it. Point extraction at an uploaded document. *Real inputs.*

6. **Versions + review.** Add `TreatyVersion` and `DataPoint` tables. Store each
   extraction as a draft version with one data-point row per field. Add
   `PATCH .../data-points/{key}`, `approve`, `reject`. Enforce "drafts only."
   *Now it's a workflow, not a script.*

7. **The frontend.** One `index.html` with `<div id="view">`, a `style.css`, and
   an `app.js` that: fetches `/treaties`, renders a table, and has an upload
   button. Then add the hash router and the review screen. Build it screen by
   screen. *You have a UI.*

8. **Amendments, audit, stats, providers.** Layer these on once the core loop
   works — each is an additive service + a route + a bit of UI.

9. **Tests.** Add `pytest` with a **fake** chat model (see `tests/conftest.py`)
   so the whole flow runs without an API key. Test the rules, not the AI.

10. **The Knowledge Base.** Now that you have a corpus, add a second area:
    - *Analytics* — a service that aggregates the stored fields (counts per
      category, totals per currency) + a charts page. Deterministic; no LLM.
    - *Summary* — feed those numbers to the chat model for a narrative.
    - *Ask (RAG)* — add an embeddings provider + a `treaty_chunks` table; embed
      each treaty, retrieve by cosine, answer with citations. (This is the
      heaviest piece — do it last, and keep the embedder pluggable.)

11. **The assistant & observability.** A tool-free chat endpoint grounded in the
    current treaty/portfolio, and optional MLflow tracing gated behind a flag.
    Both are additive and shouldn't touch the core loop.

The order matters: **backend first, always runnable, UI last.** Never build a
screen for an endpoint that doesn't exist yet. And keep the two "answer" paths
separate — **aggregates from data, prose from the LLM** (§8.7).

---

## 10. Glossary

- **API** — the set of URLs the backend exposes; the contract between frontend
  and backend.
- **REST** — a convention: nouns as URLs, HTTP verbs as actions.
- **JSON** — text data format identical in shape to Python dicts/lists.
- **Endpoint / route** — one URL + method handled by one function.
- **ORM** — library that maps DB rows to Python objects (SQLAlchemy).
- **Session (DB)** — a unit of work; changes are staged then `commit`ted.
- **Migration** — a change to the DB structure (here: edit `models.py` +
  `schema.sql`; a real project would use Alembic).
- **Pydantic model / schema** — a typed data shape used for validation and
  (de)serialization.
- **Dependency injection** — FastAPI supplying things (like a DB session) to
  your function automatically via `Depends`.
- **DOM** — the browser's live, editable tree of the page.
- **SPA (single-page app)** — one HTML page; JavaScript swaps the content to
  simulate multiple pages.
- **Client-side router** — JS that shows different screens based on the URL hash
  without contacting the server.
- **`fetch`** — the browser's built-in HTTP client (frontend's `requests`).
- **Template literal** — a JS backtick string with `${...}` interpolation; used
  to build HTML.
- **CSS variable** — a reusable value (like a color) defined once in `:root`.
- **Flexbox / Grid** — CSS layout systems for arranging boxes.

---

## 11. How to present it

A 5-minute narrative that lands:

1. **The problem.** "Reinsurance treaties are dense legal PDFs. Extracting the
   ~40 numbers a system needs is slow, error-prone, and must be auditable."
2. **The idea.** "AI reads the document into a defined schema, but a human
   approves every value before it's used — transparent, not a black box."
3. **The architecture.** Draw the onion (routes → services → models → DB) and
   the two-halves picture (browser SPA ↔ JSON API). "Clean seams: I could swap
   the AI vendor or rebuild the UI without touching the other side."
4. **The safeguards.** "Immutable, versioned records; a hash-chained audit trail
   you can cryptographically verify; approved-only values reach downstream
   calculations."
5. **The demo.** Upload → watch it extract → show the source quote + confidence
   on a value → correct one → approve → amend → show the diff → open the audit
   tab and hit *verify*.

Three sentences that show depth:
- "One Pydantic schema drives the AI extraction, the API, the database rows, and
  the UI — add a field in one place and the whole pipeline follows."
- "The frontend and backend share nothing but JSON over HTTP, so each can evolve
  independently."
- "Approved treaty versions are immutable; changes create new reviewable
  versions, and every transition is recorded in a tamper-evident log."

---

*Want to go deeper on any section — e.g. a line-by-line read of `app.js`, or a
hands-on exercise where you add a new data point and watch it flow end to end?
That's the fastest way to make this stick.*
