-- ReIn schema for Supabase (Postgres).
-- Run in the Supabase SQL editor, then point the app at the project's
-- connection string:
--   DATABASE_URL=postgresql+psycopg://postgres:<password>@db.<ref>.supabase.co:5432/postgres
--
-- Keep in sync with app/models.py (the ORM is the source of truth).

create table if not exists documents (
    id          varchar(36) primary key,
    filename    varchar(512) not null,
    kind        varchar(32)  not null check (kind in ('treaty', 'amendment')),
    content_text text        not null,
    sha256      varchar(64)  not null,
    uploaded_by varchar(256) not null default 'system',
    created_at  timestamptz  not null default now()
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
    effective_date     varchar(64),
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
