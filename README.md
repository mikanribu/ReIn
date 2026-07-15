# TreatyIQ — Reinsurance Treaty Parsing, Versioning & Knowledge Base

TreatyIQ parses reinsurance treaty documents with **LangChain + Claude**, maps
every extracted data point against a **defined catalogue** (with the exact
source quote, location, confidence and rationale), and stores the results in a
database (**Supabase Postgres** or SQLite) so approved values can feed
downstream calculations. Treaties can be **amended** from an
adjustment/endorsement document or manually — every change creates a new
reviewable version, and a **hash-chained audit trail** records everything.

The app has **two areas** (a header menu switches between them):

- **Treaty Review** — upload → extract → review → approve → amend, per treaty,
  human-in-the-loop and audited.
- **Knowledge Base** — works across the whole book: portfolio **analytics**, an
  AI **summary**, and semantic **Ask** (RAG Q&A with citations).

Plus a floating **chat assistant** grounded in the treaty you're viewing (or the
portfolio elsewhere), and optional **MLflow** observability.

## Core principles

1. **Transparent extraction** — nothing goes into the database as a bare value.
   Every data point carries `source_quote`, `source_location`, `confidence`
   and `rationale`, so a reviewer can verify each field against the document
   before approving.
2. **Human-in-the-loop** — an extraction produces a **draft** version. Only
   after a user approves it do the values become available to downstream
   consumers (`GET /treaties/{id}/current`). Drafts can never leak into
   calculations.
3. **Immutable versioning** — approved versions are frozen. Amendments (from a
   document or manual) copy the latest approved version, apply the changes,
   and create a *new draft* that goes through the same review/approval loop.
   The previous version is marked `superseded`, never deleted.
4. **Auditability** — every action (upload, extraction, edit, approval,
   rejection, amendment) is appended to a hash-chained audit log.
   `GET /audit/verify` re-walks the chain and detects any tampering. On
   Supabase, a database trigger additionally makes the log append-only.
5. **Aggregates from data, prose from the model** — Knowledge Base analytics
   (counts, totals) are computed deterministically in SQL/Python, *never* by the
   LLM. The AI summary and the RAG "Ask" are fed those exact numbers / retrieved
   treaties, so answers stay grounded and cite their sources.

## Architecture

```
                ┌────────────────────────────────────────────────────┐
 upload         │ FastAPI (app/api)                                  │
 PDF/DOCX/TXT ─▶│  /documents  /extractions  /treaties/*  /audit     │
                └───────┬──────────────────────────┬─────────────────┘
                        │                          │
              ┌─────────▼──────────┐    ┌──────────▼─────────────┐
              │ services/extraction│    │ services/treaties      │
              │ LangChain +        │    │ versioning, review,    │
              │ ChatAnthropic      │    │ amendments, diffs      │
              │ structured output  │    └──────────┬─────────────┘
              └─────────┬──────────┘               │
                        │              ┌───────────▼────────────┐
              ┌─────────▼──────────┐   │ services/audit         │
              │ schemas/           │   │ hash-chained log       │
              │ treaty_fields.py   │   └───────────┬────────────┘
              │ (data point        │               │
              │  catalog)          │    ┌──────────▼─────────────┐
              └────────────────────┘    │ SQLAlchemy / Postgres  │
                                        │ (Supabase) or SQLite   │
                                        └────────────────────────┘
```

### Layout

| Path | Purpose |
|---|---|
| `app/schemas/treaty_fields.py` | **The data-point catalogue** (metadata-driven: `_FIELDS` → key, category, mandatory/optional, description). Generates the treaty-level extraction model + the product/benefit/cession child models. Add a field here and extraction, `/catalog`, validation and storage all follow. |
| `app/services/extraction.py` | LangChain chains: treaty + amendment extraction (structured output, validated by Pydantic). |
| `app/services/treaties.py` | Version state machine: draft → approved/rejected, amendments, diffs, child collections. |
| `app/services/audit.py` | Append-only hash-chained audit trail + verification. |
| `app/services/llm.py` / `embeddings.py` | Construct the chat/extraction models and the embeddings model (swap provider here). |
| `app/services/analytics.py` / `summary.py` / `rag.py` / `chat.py` / `stats.py` | Knowledge Base: deterministic analytics, grounded AI summary, RAG index+Ask, the chat assistant, dashboard KPIs. |
| `app/observability.py` | Optional MLflow tracing/metrics (no-op when disabled). |
| `app/models.py` | SQLAlchemy ORM (documents, treaties, versions, data points, product/benefit/cession children, semantic chunks, audit log). |
| `app/api/` | HTTP routes (`routes_treaties`, `_documents`, `_analytics`, `_kb`, `_chat`). |
| `app/static/` | The web UI (vanilla HTML/CSS/JS single-page app + chat widget, served at `/`). |
| `scripts/reset_db.py` | Wipe & recreate all tables for a clean slate. |
| `supabase/schema.sql` | DDL for Supabase, incl. the append-only audit trigger. |
| `docs/GUIDE.md`, `docs/BACKLOG.md` | Full build walkthrough; prioritised roadmap. |
| `tests/` | End-to-end tests with a **fake LLM + fake embedder** (no API key needed). |

## Quick start

```bash
python3.13 -m venv venv && source venv/bin/activate   # use Python 3.11–3.13
pip install -r requirements.txt
cp .env.example .env            # add your ANTHROPIC_API_KEY
uvicorn app.main:app --reload
```

> Use Python **3.11–3.13**. Python 3.14 breaks some dependencies (e.g. MLflow).

Then open:

* **`http://localhost:8000/`** — the **web UI**. *Treaty Review*: upload a
  treaty, review every extracted data point next to its source quote and
  confidence, correct values inline, approve/reject, amend (document or manual)
  with an old→new diff, and browse version history and the audit trail.
  *Knowledge Base*: portfolio charts, an AI summary, bulk ingest, and semantic
  Ask. Plus the floating chat assistant. Plain HTML/JS — no build step.
* `http://localhost:8000/docs` — interactive API docs (Swagger).

To wipe all data and start fresh: `python -m scripts.reset_db`.

Run the tests (no API key required — the LLM is faked):

```bash
python -m pytest tests/ -q
```

### Using Supabase

1. Run `supabase/schema.sql` in the Supabase SQL editor.
2. `pip install "psycopg[binary]"`
3. Set in `.env`:
   `DATABASE_URL=postgresql+psycopg://postgres:<password>@db.<project-ref>.supabase.co:5432/postgres`

## Choosing providers

Everything AI runs through LangChain and is swappable via `.env`. There are
**three independent provider selectors** — you can, for example, use Anthropic
for extraction, Ollama for chat, and Azure for embeddings:

| Selector | Used for | Options |
|---|---|---|
| `EXTRACTION_LLM_PROVIDER` | parsing treaties/amendments | `anthropic` (default), `ollama`, `azure_openai` |
| `CHAT_LLM_PROVIDER` | chat assistant, RAG answers, AI summary | `anthropic`, `ollama` (default), `azure_openai` |
| `EMBEDDINGS_PROVIDER` | Knowledge Base semantic search | `ollama` (default), `azure_openai` |

Install only the integrations you use (construction lives in
`app/services/llm.py` and `embeddings.py`; a misconfigured provider fails fast
with a message naming exactly what to set):

| Provider | Install | Key `.env` |
|---|---|---|
| **Anthropic** (Claude) | `pip install langchain-anthropic` | `ANTHROPIC_API_KEY=…`, `ANTHROPIC_MODEL=claude-opus-4-8` |
| **Ollama** (local, no key) | `pip install langchain-ollama` + `ollama serve` | `OLLAMA_MODEL=llama3.1`, `OLLAMA_EMBED_MODEL=nomic-embed-text`, `OLLAMA_BASE_URL=http://localhost:11434` |
| **Azure OpenAI** | `pip install langchain-openai` | `AZURE_OPENAI_API_KEY=…`, `AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com`, `AZURE_OPENAI_DEPLOYMENT=<chat/extract deployment>`, `AZURE_OPENAI_EMBED_DEPLOYMENT=<embeddings deployment>` |

Extraction uses structured output (`with_structured_output`), supported by all
three. For Ollama chat/extraction pick a tool-capable model (`llama3.1`,
`qwen2.5`, `mistral-nemo`); for embeddings `nomic-embed-text` (or Azure
`text-embedding-3-small`). **Embedding dimensions are fixed per model**, so if
you switch embedding provider you must rebuild the KB index (a button in the
*Ask* tab).

## Observability with MLflow (optional)

MLflow gives you **model/quality observability** — traces of every LLM call plus
metrics for extraction and indexing. It is entirely opt-in and **off by
default**; when disabled, none of it runs and MLflow need not even be installed.
(This is separate from the hash-chained audit trail, which is the compliance
record.)

**What gets logged** (only when enabled):

| Operation | MLflow run | Logged |
|---|---|---|
| Treaty extraction (`POST /extractions`) | `extract:<file>` | field coverage, mean confidence, low-confidence count, duration + the LLM trace (via autolog) |
| Chat (`POST /chat`) | `chat` | the LLM trace |
| Index build (`POST /kb/reindex`, `/kb/index/{id}`) | `kb.reindex` / `kb.index` | chunks, chars, dimension, duration, embedding provider/model |

No document text or treaty content is logged — only metrics and the trace MLflow
autolog captures. See `app/observability.py`.

### Enable it

```bash
pip install mlflow            # not in requirements.txt (optional extra)
```
`.env`:
```bash
MLFLOW_ENABLED=true
MLFLOW_TRACKING_URI=sqlite:///mlflow.db     # SQLite backend — no server needed
MLFLOW_EXPERIMENT=treaty-extraction
```
Then use the app normally. MLflow initializes **lazily on the first traced
operation** (never at startup, so a misconfigured tracking store can't block the
app from booting). Do an extraction or a reindex to create the first run.

### View the runs

In a **second terminal, from the repo root** (so the relative DB path matches):
```bash
mlflow ui --backend-store-uri sqlite:///mlflow.db --port 5001
```
Open <http://localhost:5001>. Use the **Traces** tab for LLM calls and the
**Runs** table for the metrics above (sort by `mean_confidence` to find weak
extractions, or compare `kb.reindex` runs across embedding models).

### Gotchas we hit (so you don't)

- **Use the SQLite (or Postgres) backend, not the file store.** MLflow 3.x rejects
  `file:./mlruns` — use `sqlite:///mlflow.db`. The slashes matter: three = a
  relative file, so run the app and `mlflow ui` from the same directory.
- **Don't run `mlflow ui` against the same `mlflow.db` while hammering the app** —
  a SQLite lock can make the first traced request slow. If it hangs, quit the UI
  or `mv mlflow.db mlflow.db.bak` and retry.
- **Python 3.13, not 3.14.** MLflow doesn't run on Python 3.14 yet
  (`importlib.abc.Traversable` was removed); build your venv on 3.13.
- **Turn it off in production** unless you're pointing at a secured, remote
  tracking server — traces include prompts/responses (treaty content).

## Workflow walkthrough

```bash
# 1. Upload a treaty document (.pdf, .docx, .txt)
curl -F "file=@samples/sample_treaty.txt" -F kind=treaty -F actor=clementine \
     http://localhost:8000/documents
# -> {"id": "<DOC_ID>", ...}

# 2. Run the extraction -> creates the treaty + version 1 (DRAFT)
curl -X POST http://localhost:8000/extractions \
     -H 'Content-Type: application/json' \
     -d '{"document_id": "<DOC_ID>", "actor": "clementine"}'
# -> every data point with value + source_quote + location + confidence + rationale

# 3. Review: correct a treaty-level data point if needed (audited)
curl -X PATCH http://localhost:8000/treaties/<TID>/versions/1/data-points/reinsurer_name \
     -H 'Content-Type: application/json' \
     -d '{"value": "Helvetia Re, Zurich", "note": "per signed slip", "actor": "clementine"}'

# 4. Approve -> values become available downstream
curl -X POST http://localhost:8000/treaties/<TID>/versions/1/approve \
     -H 'Content-Type: application/json' -d '{"actor": "clementine"}'
curl http://localhost:8000/treaties/<TID>/current     # flat values for calculations

# 5a. Amend from an adjustment document -> new DRAFT version with changes flagged
curl -F "file=@samples/sample_amendment.txt" -F kind=amendment http://localhost:8000/documents
curl -X POST http://localhost:8000/treaties/<TID>/amendments/from-document \
     -H 'Content-Type: application/json' \
     -d '{"document_id": "<AMEND_DOC_ID>", "actor": "clementine"}'
curl http://localhost:8000/treaties/<TID>/versions/2/diff   # exactly what changed
curl -X POST http://localhost:8000/treaties/<TID>/versions/2/approve \
     -H 'Content-Type: application/json' -d '{"actor": "clementine"}'

# 5b. ...or amend manually (treaty-level fields; children carry forward)
curl -X POST http://localhost:8000/treaties/<TID>/amendments/manual \
     -H 'Content-Type: application/json' \
     -d '{"changes": {"party_share_percentage": 70}, "reason": "renewal terms", "actor": "clementine"}'

# 6. Audit
curl http://localhost:8000/treaties/<TID>/audit   # full trail for this treaty
curl http://localhost:8000/audit/verify           # proves the trail is untampered

# 7. Knowledge Base (across all treaties)
curl http://localhost:8000/analytics/portfolio          # deterministic breakdowns
curl -X POST http://localhost:8000/kb/reindex           # build the semantic index
curl -X POST http://localhost:8000/kb/ask \
     -H 'Content-Type: application/json' \
     -d '{"question": "Which treaties are quota share?"}'   # RAG answer + citations
```

> **Note on children:** products, benefits and cession rules/layers are
> one-to-many child collections (see `version["products"]`, `["cession_rules"]`,
> etc.). Treaty-level fields amend by key as above; a child collection is
> replaced *wholesale* by an amendment that returns its full new list.

## API summary

| Method & path | Purpose |
|---|---|
| `POST /documents` · `GET /documents` | Upload a document / list all uploaded documents |
| `GET /documents/{id}/file` | View/download the original uploaded file (PDFs render inline) |
| `GET /catalog` · `GET /catalog/fields` | Data-point catalogue / catalogue with metadata (category, mandatory) |
| `POST /extractions` | Parse a treaty document → new treaty, draft v1 (+ product/benefit/cession children) |
| `GET /treaties`, `GET /treaties/{id}` | List/inspect treaties and their versions |
| `GET /treaties/{id}/versions/{n}` | Full version detail incl. all data points + provenance |
| `GET /treaties/{id}/versions/{n}/diff` | Changes vs the parent version |
| `PATCH .../versions/{n}/data-points/{key}` | Correct a data point on a draft (audited) |
| `POST .../versions/{n}/approve` / `.../reject` | Review decision; approval supersedes the prior version |
| `POST /treaties/{id}/amendments/from-document` | Parse an adjustment document → new draft version |
| `POST /treaties/{id}/amendments/manual` | Apply user-supplied changes → new draft version |
| `GET /treaties/{id}/current` | Latest **approved** values (+ children), for downstream calculation |
| `GET /treaties/{id}/audit`, `GET /audit`, `GET /audit/verify` | Audit trail & integrity check |
| `GET /stats` | Dashboard KPI counts |
| `GET /analytics/portfolio` · `POST /analytics/summary` | Portfolio breakdowns / grounded AI summary |
| `POST /kb/reindex` · `GET /kb/status` · `GET /kb/indexed` · `POST /kb/index/{id}` | Build / inspect the semantic index |
| `POST /kb/ask` | RAG Q&A across the corpus, with citations |
| `POST /chat` | Treaty-aware / portfolio chat assistant (no web access) |

## Maintaining the backend

* **Add/change a data point** → edit `_FIELDS` in
  `app/schemas/treaty_fields.py` (key, requirement, category, description). The
  extraction model, `/catalog`(`/fields`), manual-edit validation and storage all
  derive from it. Existing versions keep their historical fields.
* **Change a model / provider** → env vars (`EXTRACTION_LLM_PROVIDER`,
  `CHAT_LLM_PROVIDER`, `EMBEDDINGS_PROVIDER` and the per-provider keys/models);
  construction lives only in `app/services/llm.py` and `embeddings.py`.
* **Change extraction behaviour** → prompts live in
  `app/services/extraction.py`.
* **Business rules** (who can approve, extra states) → `app/services/treaties.py`
  is the single state machine.
* **Observability** → optional MLflow, off by default (see the section above and
  `app/observability.py`).
* **Testing without spend** → tests inject a fake LLM **and a fake embedder** via
  FastAPI dependency overrides (`tests/conftest.py`); copy that pattern for new
  tests.

See `docs/GUIDE.md` for the full end-to-end walkthrough and `docs/BACKLOG.md`
for the roadmap.
