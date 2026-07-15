-- ReIn schema for Supabase (Postgres).
-- Run in the Supabase SQL editor, then point the app at the project's
-- connection string:
--   DATABASE_URL=postgresql+psycopg://postgres:<password>@db.<ref>.supabase.co:5432/postgres
--
-- Keep in sync with app/models.py (the ORM is the source of truth).

create table if not exists documents (
    id            varchar(36) primary key,
    filename      varchar(512) not null,
    kind          varchar(32)  not null check (kind in ('treaty', 'amendment')),
    content_text  text        not null,
    content_bytes bytea,                       -- original uploaded file (for viewing)
    content_type  varchar(128),                -- MIME type of the original file
    sha256        varchar(64)  not null,
    uploaded_by   varchar(256) not null default 'system',
    created_at    timestamptz  not null default now()
);
create index if not exists idx_documents_sha256 on documents (sha256);

create table if not exists treaties (
    id         varchar(36) primary key,
    reference  varchar(256) not null unique,
    name       varchar(512) not null,
    created_at timestamptz  not null default now()
);

create table if not exists treaty_versions (
    id                 varchar(36) primary key,
    treaty_id          varchar(36) not null references treaties (id),
    version_number     integer     not null,
    status             varchar(32) not null default 'draft'
                       check (status in ('draft', 'approved', 'rejected', 'superseded')),
    origin             varchar(32) not null
                       check (origin in ('extraction', 'amendment_document', 'manual_amendment')),
    source_document_id varchar(36) references documents (id),
    parent_version_id  varchar(36) references treaty_versions (id),
    change_summary     text,
    effective_date     date,
    created_by         varchar(256) not null default 'system',
    created_at         timestamptz  not null default now(),
    reviewed_by        varchar(256),
    reviewed_at        timestamptz,
    review_note        text,
    unique (treaty_id, version_number)
);
create index if not exists idx_versions_treaty on treaty_versions (treaty_id);

create table if not exists data_points (
    id              varchar(36) primary key,
    version_id      varchar(36)  not null references treaty_versions (id) on delete cascade,
    field_key       varchar(128) not null,
    field_label     varchar(256) not null,
    value           jsonb,
    status          varchar(32)  not null default 'extracted',
    source_quote    text,
    source_location varchar(512),
    confidence      double precision,
    rationale       text,
    updated_at      timestamptz  not null default now(),
    unique (version_id, field_key)
);
create index if not exists idx_data_points_version on data_points (version_id);
create index if not exists idx_data_points_key on data_points (field_key);

-- Relational child collections (one row per product / benefit / cession layer).
create table if not exists treaty_products (
    id                   varchar(36) primary key,
    version_id           varchar(36) not null references treaty_versions (id) on delete cascade,
    product_code         varchar(128),
    product_name         varchar(256),
    product_type         varchar(128),
    product_scope_status varchar(64),
    seq                  integer default 0,
    source_quote         text,
    source_location      varchar(512),
    confidence           double precision
);
create index if not exists idx_products_version on treaty_products (version_id);

create table if not exists treaty_benefits (
    id              varchar(36) primary key,
    version_id      varchar(36) not null references treaty_versions (id) on delete cascade,
    benefit_code    varchar(128),
    benefit_name    varchar(256),
    benefit_type    varchar(128),
    seq             integer default 0,
    source_quote    text,
    source_location varchar(512),
    confidence      double precision
);
create index if not exists idx_benefits_version on treaty_benefits (version_id);

create table if not exists cession_rules (
    id                              varchar(36) primary key,
    version_id                      varchar(36) not null references treaty_versions (id) on delete cascade,
    country_code                    varchar(16),
    cession_effective_start_date    varchar(32),
    cession_effective_end_date      varchar(32),
    policy_inception_start_date     varchar(32),
    policy_inception_end_date       varchar(32),
    cession_basis                   varchar(64),
    layer_number                    integer,
    layer_name                      varchar(256),
    cedant_retention_ratio          double precision,
    reinsurer_cession_ratio         double precision,
    layer_attachment_amount         double precision,
    layer_limit_amount              double precision,
    layer_detachment_amount         double precision,
    maximum_cedant_retention_amount double precision,
    aggregation_basis               varchar(64),
    priority_order                  integer,
    seq                             integer default 0,
    source_quote                    text,
    source_location                 varchar(512),
    confidence                      double precision
);
create index if not exists idx_cession_version on cession_rules (version_id);

-- Semantic index for Knowledge Base "Ask" (RAG). pgvector is the production
-- upgrade for the embedding column; JSON works for a portable default.
create table if not exists treaty_chunks (
    id               varchar(36) primary key,
    treaty_id        varchar(36) not null references treaties (id) on delete cascade,
    treaty_reference varchar(256) not null,
    treaty_name      varchar(512) not null,
    chunk_index      integer default 0,
    content          text not null,
    embedding        jsonb not null,
    embedding_model  varchar(128) not null,
    created_at       timestamptz not null default now()
);
create index if not exists idx_chunks_treaty on treaty_chunks (treaty_id);
create index if not exists idx_chunks_model on treaty_chunks (embedding_model);

create table if not exists audit_log (
    id          serial primary key,
    timestamp   timestamptz  not null default now(),
    actor       varchar(256) not null,
    action      varchar(64)  not null,
    entity_type varchar(64)  not null,
    entity_id   varchar(36)  not null,
    treaty_id   varchar(36),
    details     jsonb,
    prev_hash   varchar(64)  not null,
    entry_hash  varchar(64)  not null
);
create index if not exists idx_audit_treaty on audit_log (treaty_id);

-- The audit log must be append-only. Enforce at the database level so even a
-- compromised application role cannot rewrite history.
create or replace function audit_log_block_mutation() returns trigger as $$
begin
    raise exception 'audit_log is append-only';
end;
$$ language plpgsql;

drop trigger if exists trg_audit_no_update on audit_log;
create trigger trg_audit_no_update
    before update or delete on audit_log
    for each row execute function audit_log_block_mutation();
