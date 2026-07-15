# TreatyIQ — Backlog

Candidate features and enhancements, grouped by theme. Each item notes rough
**effort** (S ≈ hours, M ≈ a day or two, L ≈ multi-day / touches many layers)
and **priority** (🔴 high / 🟡 medium / 🟢 nice-to-have). Nothing here is
committed work — it's the menu to prioritise from.

> Legend: `[ ]` not started · `[~]` in progress · `[x]` done

---

## 1. Data model & extraction

- [x] 🔴 **L — Relational products / benefits / layers (MVP).** ✅ Done. Products,
  benefits and cession rules/layers are now one-to-many child tables
  (`TreatyProduct` / `TreatyBenefit` / `CessionRule`), flat lists at treaty
  level. Extraction returns nested lists; review shows child sections; analytics
  and RAG read the child rows. Amendments **replace a collection wholesale**.
- [~] 🟡 **L — Nested (per-row) amendment addressing.** Partly done.
  ✅ **Draft child editing** landed: products / benefits / cession-layer rows can
  be edited, added and removed per-row on a *draft* version (a full-field form
  surfaces missing values to fill), via `POST/PATCH/DELETE
  /treaties/{id}/versions/{n}/children/{collection}[/{row_id}]`, draft-only and
  audited (`child_row.added|edited|deleted`).
  ⏳ **Still open:** addressing a specific child field through the *amendment*
  path on an approved version (a child-row addressing scheme in `AmendedField` +
  granular collection diff), so amendments needn't replace a collection wholesale.
- [ ] 🟡 **M — Configurable classification dimensions.** Add an explicit
  category/product/segment classification step (a couple of extracted tags) so
  analytics can group by business-defined dimensions, and let users choose which
  dimensions to chart.
- [ ] 🟡 **M — OCR fallback for scanned PDFs.** Scanned/image PDFs currently
  yield little/no text. Detect low text yield and warn, or run OCR (e.g.
  Tesseract) before extraction.
- [ ] 🟢 **S — Include the internal-id fields if wanted.** `treaty_id`,
  `product_id`, `benefit_id`, `cession_rule_id` are intentionally excluded from
  extraction (system-generated). Revisit if a code-like id should be pulled from
  the document.
- [ ] 🟡 **M — Real migrations (Alembic).** Replace `create_all` + `schema.sql`
  with Alembic so schema changes (like the relational restructure) are versioned
  and safe on Postgres.

## 2. Knowledge Base & RAG

- [ ] 🟡 **M — pgvector for production.** The vector store is JSON + in-Python
  cosine (fine for dev/SQLite). Swap to pgvector on Supabase for real scale.
- [ ] 🟡 **M — Richer chunking.** Currently one structured chunk per treaty. Add
  document-text chunking (and multiple chunks per treaty) for better recall on
  qualitative questions; consider overlap and per-field chunks.
- [ ] 🟡 **M — Retrieval-quality evaluation.** A small gold set of
  question → expected-treaty pairs, scored and logged (per embedding model) so
  model choice becomes quantitative. Needs a running embedder.
- [ ] 🟢 **S — Per-treaty KB management.** Ability to exclude a treaty from the
  corpus / index, or maintain a separately curated KB, if "one corpus = all
  treaties" ever needs an exception.
- [ ] 🟢 **S — Answer streaming.** Stream chat / Ask / summary tokens for better
  UX on slower local models.

## 3. UX & frontend

- [x] 🟡 **M — Review-screen metadata surfacing.** ✅ Done. The review screen now
  fetches `/catalog/fields` and shows a required marker (`*`) on mandatory fields,
  flags missing strictly-mandatory values with a "missing required" badge (kept
  visible even under *hide fields not in document*), adds a per-version
  completeness summary ("N of M required fields missing") and a "Missing required"
  status filter. Child tables (products / benefits / cession) mark required
  columns and flag empty mandatory cells too. Category grouping itself was moot:
  post-relational, the flat data-point table is all Treaty-category, and products
  / benefits / cession already render as their own category sections.
- [ ] 🟡 **M — Multi-file / mixed bulk upload.** Finish the "Multiple treaties
  upload (coming soon)" tile: upload many treaties *and* amendments at once, with
  automatic mapping of each amendment to the correct treaty.
- [ ] 🟢 **S — Export / reporting.** Export a treaty summary or the portfolio
  analytics to PDF/Excel for client deliverables.
- [ ] 🟢 **M — Dark mode.** Theme toggle with a persisted preference; style both
  light and dark.
- [ ] 🟢 **S — Pagination & search on long lists.** `/treaties`, `/documents`,
  `/audit` are unpaginated; add server-side pagination for large books.

## 4. Workflow & security

- [ ] 🔴 **L — Authentication & identity.** Every endpoint trusts a self-asserted
  `actor` string. Add real auth/SSO so the audit trail's identity is trustworthy
  before any non-POC use.
- [ ] 🟡 **M — Maker–checker review workflow.** Separate submitter from approver,
  support multiple reviewers, per-field comments, and an approval queue.
- [ ] 🟡 **S — Concurrency guard on version numbers.** Two parallel amendments can
  race on `version_number`; add retry-on-conflict around the unique constraint.
- [ ] 🟢 **S — Rate limiting / cost guardrails** on the LLM-backed endpoints.

## 5. Observability & ops

- [ ] 🟡 **S — Batch MLflow runs for ingest.** With tracing on, bulk-ingesting N
  files creates 2N runs (extract + kb.index). Option to nest per-file metrics as
  steps under one parent run per ingest batch.
- [ ] 🟢 **S — Amendment extraction metrics.** Instrument the amendment path like
  treaty extraction (coverage/confidence), and give it a named MLflow run.
- [ ] 🟢 **S — Embedding-call tracing.** Autolog doesn't trace `embed_*` calls;
  add lightweight spans if embedding latency/quality needs debugging.
- [ ] 🟡 **S — CI pipeline.** GitHub Actions to run `pytest` (and a lint) on every
  PR to the branch.
- [ ] 🟢 **S — Structured logging & health/readiness.** JSON logs and a richer
  `/health` (DB reachable, provider configured) for deployment.

## 6. Scale & performance

- [ ] 🟡 **L — Background ingestion.** Bulk ingest is client-driven and
  sequential (~40s + cost per treaty). For hundreds+, move extraction/indexing to
  a background worker/queue with durable progress.
- [ ] 🟢 **S — Cheaper/faster extraction model for KB ingest.** Use a smaller
  model for bulk ingest where per-field review isn't the immediate goal.
- [ ] 🟢 **S — Query tuning.** Audit N+1s and add eager-loading/indexes as the
  corpus grows (analytics already uses `selectinload`).

## 7. Deployment & hosting

The app currently runs locally (uvicorn + SQLite). Getting it to a shared/
production environment:

- [ ] 🔴 **M — Containerise.** A `Dockerfile` (uvicorn/gunicorn serving the API
  + the static UI) and a `docker-compose` for local prod-like runs. Pin the
  provider extras actually used.
- [ ] 🔴 **M — Managed Postgres (Supabase).** Point `DATABASE_URL` at Supabase,
  apply `supabase/schema.sql` (or Alembic), and verify the app on Postgres — the
  audit trigger and `jsonb`/vector columns especially. Adopt **Alembic** so schema
  changes deploy safely.
- [ ] 🔴 **M — Host the API.** Deploy the container to a platform (Fly.io /
  Render / Azure Container Apps / a VM behind Nginx). HTTPS/TLS, a domain, health
  checks, and env-var/secret injection (no keys in the image).
- [ ] 🟡 **M — LLM/embeddings in the cloud.** Ollama needs a model server —
  either run it on a GPU/CPU instance, or switch chat/extraction to Anthropic and
  embeddings to **Azure `text-embedding-3-small`** so nothing self-hosted is
  required. Decide per data-residency needs.
- [ ] 🟡 **S — Hosted MLflow (if used).** Run a tracking server with a Postgres
  backend + artifact store, access-controlled; set `MLFLOW_TRACKING_URI` to it.
  Otherwise keep tracing off in prod.
- [ ] 🟡 **M — CI/CD.** GitHub Actions to test, build the image, and deploy on
  merge; environment separation (dev / staging / prod) with per-env config.
- [ ] 🟢 **S — Prod ops.** Structured logging, error tracking (e.g. Sentry),
  backups for Postgres, and a documented restore/reset runbook.

> Note: several security items (🔴 **Authentication & identity**, rate limiting)
> in §4 are effectively **deployment blockers** — don't expose the app publicly
> while `actor` is self-asserted.

---

## Recently delivered (for context)

- **Relational products / benefits / cession-layers** (MVP): child tables,
  nested extraction, review sections, wholesale-replace amendments.
- Two-area app: **Treaty Review** + **Knowledge Base** (analytics, AI summary,
  RAG Ask with citations).
- Treaty-aware **chat assistant** (tool-free, grounded, citations).
- **Metadata-driven catalogue** (category + mandatory/optional), life-reinsurance
  field list, generated extraction model.
- Pluggable **embeddings** provider (Ollama / Azure); per-treaty **KB index flag**
  + auto-index on ingest; **uploaded-documents** list.
- Optional **MLflow** tracing + extraction/index metrics.
- **reset_db** script for a clean slate; input hardening (chat caps, upload
  limit); demo polish (logo, KPI tiles, empty states, sample button).
