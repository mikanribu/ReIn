# ReIn — Reinsurance Treaty Parsing & Versioning

ReIn parses reinsurance treaty documents with **LangChain + Claude**, maps every
extracted data point against a **defined catalog** (with the exact source quote,
location, confidence and rationale), and stores the results in a database
(**Supabase Postgres** or SQLite) so approved values can feed downstream
calculations. Treaties can be **amended** from an adjustment/endorsement
document or manually — every change creates a new reviewable version, and a
**hash-chained audit trail** records everything.

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
| `app/schemas/treaty_fields.py` | **The data-point catalog.** One Pydantic model defines every field the LLM extracts. Add a field here and the extraction, API catalog, validation and storage all follow. |
| `app/services/extraction.py` | LangChain chains: treaty extraction and amendment extraction (structured output, validated by Pydantic). |
| `app/services/treaties.py` | Version state machine: draft → approved/rejected, amendments, diffs. |
| `app/services/audit.py` | Append-only hash-chained audit trail + verification. |
| `app/services/llm.py` | Single place the chat model is constructed (swap model/provider here). |
| `app/models.py` | SQLAlchemy ORM (documents, treaties, versions, data points, audit log). |
| `app/api/` | HTTP routes. |
| `supabase/schema.sql` | DDL for Supabase, incl. the append-only audit trigger. |
| `tests/` | End-to-end workflow tests with a **fake LLM** (no API key needed). |

## Quick start

```bash
pip install -r requirements.txt
cp .env.example .env            # add your ANTHROPIC_API_KEY
uvicorn app.main:app --reload   # interactive docs at http://localhost:8000/docs
```

Run the tests (no API key required — the LLM is faked):

```bash
python -m pytest tests/ -q
```

### Using Supabase

1. Run `supabase/schema.sql` in the Supabase SQL editor.
2. `pip install "psycopg[binary]"`
3. Set in `.env`:
   `DATABASE_URL=postgresql+psycopg://postgres:<password>@db.<project-ref>.supabase.co:5432/postgres`

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

# 3. Review: correct a data point if needed (audited)
curl -X PATCH http://localhost:8000/treaties/<TID>/versions/1/data-points/broker \
     -H 'Content-Type: application/json' \
     -d '{"value": "Meridian Re Brokers Ltd, London", "note": "per signed slip", "actor": "clementine"}'

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

# 5b. ...or amend manually
curl -X POST http://localhost:8000/treaties/<TID>/amendments/manual \
     -H 'Content-Type: application/json' \
     -d '{"changes": {"minimum_premium": 11500000}, "reason": "renewal terms", "actor": "clementine"}'

# 6. Audit
curl http://localhost:8000/treaties/<TID>/audit   # full trail for this treaty
curl http://localhost:8000/audit/verify           # proves the trail is untampered
```

## API summary

| Method & path | Purpose |
|---|---|
| `POST /documents` | Upload a treaty or amendment document (PDF/DOCX/TXT) |
| `GET /catalog` | The defined data-point catalog |
| `POST /extractions` | Parse a treaty document → new treaty, draft v1 |
| `GET /treaties`, `GET /treaties/{id}` | List/inspect treaties and their versions |
| `GET /treaties/{id}/versions/{n}` | Full version detail incl. all data points + provenance |
| `GET /treaties/{id}/versions/{n}/diff` | Changes vs the parent version |
| `PATCH .../versions/{n}/data-points/{key}` | Correct a data point on a draft (audited) |
| `POST .../versions/{n}/approve` / `.../reject` | Review decision; approval supersedes the prior version |
| `POST /treaties/{id}/amendments/from-document` | Parse an adjustment document → new draft version |
| `POST /treaties/{id}/amendments/manual` | Apply user-supplied changes → new draft version |
| `GET /treaties/{id}/current` | Latest **approved** values, flat, for downstream calculation |
| `GET /treaties/{id}/audit`, `GET /audit`, `GET /audit/verify` | Audit trail & integrity check |

## Maintaining the backend

* **Add/change a data point** → edit `TreatyExtraction` in
  `app/schemas/treaty_fields.py` (one field with a good description). The LLM
  prompt schema, `/catalog`, manual-edit validation and storage all derive
  from it. Existing versions keep their historical fields.
* **Change the model** → `ANTHROPIC_MODEL` env var; construction logic lives
  only in `app/services/llm.py`.
* **Change extraction behavior** → prompts live in
  `app/services/extraction.py`.
* **Business rules** (who can approve, extra states) → `app/services/treaties.py`
  is the single state machine.
* **Testing without spend** → tests inject a fake LLM via FastAPI dependency
  override (`tests/conftest.py`); copy that pattern for new tests.
