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
| Upload a document | `POST /documents` |
| Run extraction | `POST /extractions` |
| Fix one data point | `PATCH /treaties/{id}/versions/1/data-points/limit` |
| Approve a version | `POST /treaties/{id}/versions/1/approve` |
| Dashboard numbers | `GET /stats` |

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
│   ├── main.py               ← creates the FastAPI app, wires routes, serves the UI
│   ├── config.py             ← all settings (DB URL, which LLM, API keys)
│   ├── database.py           ← DB engine + "give me a session" helper
│   ├── models.py             ← the database tables, as Python classes (ORM)
│   │
│   ├── api/                  ← the HTTP layer (URL handlers = "routes")
│   │   ├── routes_documents.py   ← upload / fetch / view a document
│   │   └── routes_treaties.py    ← extract, review, approve, amend, stats, audit
│   │
│   ├── services/             ← the business logic (no HTTP here)
│   │   ├── documents.py          ← turn an uploaded file into plain text
│   │   ├── llm.py                ← build the AI model (Anthropic/Ollama/Azure)
│   │   ├── extraction.py         ← ask the AI to fill the data-point schema
│   │   ├── treaties.py           ← versioning, review, amendments (the core)
│   │   ├── audit.py              ← the hash-chained audit trail
│   │   └── errors.py             ← turn AI/network failures into clean HTTP errors
│   │
│   ├── schemas/              ← data *shapes* (Pydantic models), not tables
│   │   ├── treaty_fields.py      ← THE data-point catalog (what to extract)
│   │   └── api.py                ← request/response shapes for the API
│   │
│   └── static/               ← the frontend (served as-is to the browser)
│       ├── index.html            ← the single HTML page
│       ├── style.css             ← all the styling
│       └── app.js                ← the entire UI logic (routing + rendering)
│
├── tests/                    ← automated tests (pytest)
│   ├── conftest.py               ← shared setup + a FAKE AI so tests need no key
│   └── test_*.py                 ← one file per area
│
├── scripts/                  ← standalone diagnostics (not part of the server)
├── samples/                  ← example treaty + amendment documents
├── supabase/schema.sql       ← the same tables, as SQL, for Postgres/Supabase
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
- `models.py` — five tables as classes: `Document`, `Treaty`, `TreatyVersion`,
  `DataPoint`, `AuditLog`. Also the status/origin constants.

**API layer**
- `routes_documents.py` — `POST /documents` (upload), `GET /documents/{id}`,
  `/text`, `/file` (view the original).
- `routes_treaties.py` — everything else: `/catalog`, `/stats`, `/extractions`,
  the treaty/version reads, `PATCH` a data point, approve/reject, the two
  amendment endpoints, `/current`, and the audit endpoints.

**Service layer**
- `documents.py` — `extract_text()` (PDF via pypdf, DOCX via docx2txt, TXT
  directly) and `sha256_hex()`.
- `llm.py` — `get_chat_model()` returns a LangChain chat model for whichever
  provider `LLM_PROVIDER` selects. Lazy imports so you only install what you use.
- `extraction.py` — two functions that send the document text to the model and
  get back a validated Pydantic object (treaty extraction / amendment changes).
- `treaties.py` — the heart: create a treaty from an extraction, edit/approve/
  reject a draft, create amendment versions, diff versions. All the rules live
  here.
- `audit.py` — `record()` appends a hash-chained entry; `verify_chain()`
  re-walks it to detect tampering.
- `errors.py` — a context manager that maps AI/network exceptions to friendly
  HTTP errors instead of raw 500s.

**Schemas**
- `treaty_fields.py` — `TreatyExtraction`: one Pydantic class listing every data
  point to extract, each wrapped in `ExtractedField` (value + source quote +
  location + confidence + rationale). Change this file and the whole app follows.
- `api.py` — the request bodies and response shapes (`VersionDetail`,
  `StatsOut`, etc.). These define what the API accepts and returns.

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

The five tables and how they relate:
```
Document        (an uploaded file: text + original bytes + sha256)
Treaty  1───*  TreatyVersion  1───*  DataPoint
                    │                    (one row per field per version, with provenance)
                    └── source_document_id → Document
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

### 8.1 One schema drives extraction, validation, storage, and the UI

`TreatyExtraction` in `schemas/treaty_fields.py` is the **single source of
truth** for "what is a treaty's data." From that one class:
- LangChain derives the JSON schema it forces the AI to fill,
- the `/catalog` endpoint lists the fields,
- manual edits are validated against the field keys,
- each field becomes a `DataPoint` row,
- the UI renders a row per field.

Add a field to that class and the entire pipeline picks it up. That's the
payoff of schema-driven design — say this in a presentation and people nod.

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
same code runs on SQLite locally and Supabase Postgres in production), the LLM
provider and keys, token limits. No secrets in code; no code changes to deploy.

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

The order matters: **backend first, always runnable, UI last.** Never build a
screen for an endpoint that doesn't exist yet.

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
