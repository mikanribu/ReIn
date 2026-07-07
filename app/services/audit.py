"""Append-only, hash-chained audit trail.

Every write to the system goes through ``record``. Each entry's hash covers
the previous entry's hash plus the entry's own content, so retroactive
modification or deletion of any entry breaks the chain — verifiable at any
time with ``verify_chain``.
"""
import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditLog, utcnow

GENESIS_HASH = "0" * 64


def _ts_str(dt: datetime) -> str:
    """Normalize to naive UTC so the hash survives round-trips through
    databases that do or don't preserve timezone info (SQLite vs Postgres)."""
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.isoformat()


def _compute_hash(prev_hash: str, timestamp: str, actor: str, action: str,
                  entity_type: str, entity_id: str, details: dict | None) -> str:
    payload = json.dumps(
        {
            "prev": prev_hash,
            "ts": timestamp,
            "actor": actor,
            "action": action,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "details": details,
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def record(
    db: Session,
    *,
    actor: str,
    action: str,
    entity_type: str,
    entity_id: str,
    treaty_id: str | None = None,
    details: dict | None = None,
) -> AuditLog:
    """Append an audit entry. Caller is responsible for the commit."""
    last = db.execute(select(AuditLog).order_by(AuditLog.id.desc()).limit(1)).scalar_one_or_none()
    prev_hash = last.entry_hash if last else GENESIS_HASH
    ts = utcnow()
    entry = AuditLog(
        timestamp=ts,
        actor=actor,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        treaty_id=treaty_id,
        details=details,
        prev_hash=prev_hash,
        entry_hash=_compute_hash(prev_hash, _ts_str(ts), actor, action, entity_type, entity_id, details),
    )
    db.add(entry)
    db.flush()
    return entry


def verify_chain(db: Session) -> tuple[bool, int, int | None]:
    """Re-walk the whole chain. Returns (valid, entries_checked, first_broken_id)."""
    entries = db.execute(select(AuditLog).order_by(AuditLog.id)).scalars().all()
    prev_hash = GENESIS_HASH
    for e in entries:
        expected = _compute_hash(
            prev_hash, _ts_str(e.timestamp), e.actor, e.action, e.entity_type, e.entity_id, e.details
        )
        if e.prev_hash != prev_hash or e.entry_hash != expected:
            return False, len(entries), e.id
        prev_hash = e.entry_hash
    return True, len(entries), None
