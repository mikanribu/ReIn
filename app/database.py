"""Database engine and session management (SQLAlchemy 2.0)."""
from collections.abc import Iterator

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


def _engine_kwargs(url: str) -> dict:
    # SQLite needs this flag to be usable from FastAPI's thread pool.
    if url.startswith("sqlite"):
        return {"connect_args": {"check_same_thread": False}}
    return {"pool_pre_ping": True}


_engine = None
_SessionLocal: sessionmaker | None = None


def get_engine():
    global _engine, _SessionLocal
    if _engine is None:
        url = get_settings().database_url
        _engine = create_engine(url, **_engine_kwargs(url))
        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)
    return _engine


def init_db() -> None:
    """Create tables if they don't exist (dev convenience; Supabase uses supabase/schema.sql)."""
    from app import models  # noqa: F401  (register mappings)

    Base.metadata.create_all(bind=get_engine())
    _maybe_migrate_sqlite_effective_date()


def _maybe_migrate_sqlite_effective_date() -> None:
    """Upgrade older local SQLite databases where treaty_versions.effective_date
    was stored as text instead of a real date column."""
    engine = get_engine()
    if engine.dialect.name != "sqlite":
        return

    columns = inspect(engine).get_columns("treaty_versions")
    effective = next((col for col in columns if col["name"] == "effective_date"), None)
    if effective is None or "date" in str(effective["type"]).lower():
        return

    with engine.begin() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
        conn.exec_driver_sql("ALTER TABLE treaty_versions RENAME TO treaty_versions_old")
        conn.exec_driver_sql(
            """
            CREATE TABLE treaty_versions (
                id                 varchar(36) primary key,
                treaty_id          varchar(36) not null references treaties (id),
                version_number     integer     not null,
                status             varchar(32) not null default 'draft',
                origin             varchar(32) not null,
                source_document_id varchar(36) references documents (id),
                parent_version_id  varchar(36) references treaty_versions (id),
                change_summary     text,
                effective_date     date,
                created_by         varchar(256) not null default 'system',
                created_at         datetime not null default (datetime('now')),
                reviewed_by        varchar(256),
                reviewed_at        datetime,
                review_note        text,
                unique (treaty_id, version_number)
            )
            """
        )
        conn.exec_driver_sql(
            """
            INSERT INTO treaty_versions (
                id, treaty_id, version_number, status, origin, source_document_id,
                parent_version_id, change_summary, effective_date, created_by,
                created_at, reviewed_by, reviewed_at, review_note
            )
            SELECT
                id, treaty_id, version_number, status, origin, source_document_id,
                parent_version_id, change_summary, effective_date, created_by,
                created_at, reviewed_by, reviewed_at, review_note
            FROM treaty_versions_old
            """
        )
        conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_versions_treaty ON treaty_versions (treaty_id)")
        conn.exec_driver_sql("DROP TABLE treaty_versions_old")
        conn.exec_driver_sql("PRAGMA foreign_keys=ON")


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a request-scoped session."""
    get_engine()
    assert _SessionLocal is not None
    db = _SessionLocal()
    try:
        yield db
    finally:
        db.close()
