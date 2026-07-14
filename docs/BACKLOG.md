# TreatyIQ — Backlog

Candidate features and enhancements, grouped by theme. Each item notes rough
**effort** (S ≈ hours, M ≈ a day or two, L ≈ multi-day / touches many layers)
and **priority** (🔴 high / 🟡 medium / 🟢 nice-to-have). Nothing here is
committed work — it's the menu to prioritise from.

> Legend: `[ ]` not started · `[~]` in progress · `[x]` done

---

## 1. Data model & extraction

- [ ] 🔴 **L — Relational products / benefits / layers.** Model multiple
  products, benefits and cession layers per treaty as real one-to-many tables
  (the catalogue's "one row per layer" intent), instead of the current flat
  single-product / layers-1–3 shape. Touches: nested extraction schema, new
  tables, review UI (sections), analytics/RAG, and most tests. *Design agreed;
  two questions open — do benefits nest under products, and confirm amendments
  version the whole treaty.*
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

- [ ] 🟡 **M — Review-screen metadata surfacing.** Group the data-point table by
  category (Treaty / Product & Benefit / Cession & Layers), show a mandatory
  marker, and flag missing-mandatory values. Makes the new catalogue metadata
  visible where reviewers work.
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

---

## Recently delivered (for context)

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
