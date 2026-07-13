"""Core treaty lifecycle: create from extraction, review, approve, amend.

State machine per version:

    draft --approve--> approved --(new approved version)--> superseded
      \\--reject--> rejected

Only drafts are editable. Amendments (from a document or manual) always
start from the latest approved version and create a *new* draft, so the
approved history is never mutated.
"""
import uuid
from datetime import date

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    DataPoint,
    DataPointStatus,
    Document,
    Treaty,
    TreatyVersion,
    VersionOrigin,
    VersionStatus,
    utcnow,
)
from app.schemas.treaty_fields import (
    FIELD_KEYS,
    AmendmentExtraction,
    TreatyExtraction,
    field_label,
)
from app.services import audit


# --------------------------------------------------------------------------
# Lookups
# --------------------------------------------------------------------------

def get_treaty(db: Session, treaty_id: str) -> Treaty:
    treaty = db.get(Treaty, treaty_id)
    if treaty is None:
        raise HTTPException(404, f"Treaty {treaty_id} not found")
    return treaty


def get_version(db: Session, treaty_id: str, version_number: int) -> TreatyVersion:
    version = db.execute(
        select(TreatyVersion).where(
            TreatyVersion.treaty_id == treaty_id,
            TreatyVersion.version_number == version_number,
        )
    ).scalar_one_or_none()
    if version is None:
        raise HTTPException(404, f"Version {version_number} of treaty {treaty_id} not found")
    return version


def latest_approved_version(db: Session, treaty_id: str) -> TreatyVersion | None:
    return db.execute(
        select(TreatyVersion)
        .where(TreatyVersion.treaty_id == treaty_id, TreatyVersion.status == VersionStatus.APPROVED)
        .order_by(TreatyVersion.version_number.desc())
        .limit(1)
    ).scalar_one_or_none()


def _next_version_number(db: Session, treaty_id: str) -> int:
    versions = db.execute(
        select(TreatyVersion.version_number).where(TreatyVersion.treaty_id == treaty_id)
    ).scalars().all()
    return (max(versions) + 1) if versions else 1


def values_dict(version: TreatyVersion) -> dict:
    return {dp.field_key: dp.value for dp in version.data_points}


def _date_text(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


# --------------------------------------------------------------------------
# Creation from extraction
# --------------------------------------------------------------------------

def create_treaty_from_extraction(
    db: Session,
    document: Document,
    extraction: TreatyExtraction,
    actor: str,
    reference_override: str | None = None,
) -> TreatyVersion:
    """Create a treaty and its first draft version from an LLM extraction."""
    extracted_ref = extraction.treaty_reference.value
    reference = reference_override or (
        str(extracted_ref) if extracted_ref else f"TREATY-{uuid.uuid4().hex[:8].upper()}"
    )
    existing = db.execute(select(Treaty).where(Treaty.reference == reference)).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            409,
            f"A treaty with reference '{reference}' already exists (id={existing.id}). "
            "To change it, use the amendment endpoints; to create a separate treaty, "
            "pass a different 'treaty_reference'.",
        )

    name = str(extraction.treaty_name.value or reference)
    treaty = Treaty(reference=reference, name=name)
    db.add(treaty)
    db.flush()

    version = TreatyVersion(
        treaty_id=treaty.id,
        version_number=1,
        status=VersionStatus.DRAFT,
        origin=VersionOrigin.EXTRACTION,
        source_document_id=document.id,
        created_by=actor,
    )
    db.add(version)
    db.flush()

    for key in TreatyExtraction.model_fields:
        f = getattr(extraction, key)
        db.add(
            DataPoint(
                version_id=version.id,
                field_key=key,
                field_label=field_label(key),
                value=f.value,
                status=DataPointStatus.EXTRACTED if f.value is not None else DataPointStatus.NOT_FOUND,
                source_quote=f.source_quote,
                source_location=f.source_location,
                confidence=f.confidence,
                rationale=f.rationale,
            )
        )

    audit.record(
        db,
        actor=actor,
        action="treaty.extracted",
        entity_type="treaty_version",
        entity_id=version.id,
        treaty_id=treaty.id,
        details={"document_id": document.id, "reference": reference, "version": 1},
    )
    db.commit()
    db.refresh(version)
    return version


# --------------------------------------------------------------------------
# Review: edit / approve / reject (drafts only)
# --------------------------------------------------------------------------

def _require_draft(version: TreatyVersion) -> None:
    if not version.is_editable:
        raise HTTPException(
            409,
            f"Version {version.version_number} is '{version.status}' and immutable. "
            "Create an amendment to change an approved treaty.",
        )


def edit_data_point(
    db: Session,
    version: TreatyVersion,
    field_key: str,
    new_value,
    actor: str,
    note: str | None,
) -> DataPoint:
    _require_draft(version)
    if field_key not in FIELD_KEYS:
        raise HTTPException(422, f"Unknown field_key '{field_key}'. See GET /catalog for valid keys.")
    dp = next((d for d in version.data_points if d.field_key == field_key), None)
    if dp is None:  # defensive; versions always carry the full catalog
        raise HTTPException(404, f"Data point '{field_key}' not found on this version")

    old_value = dp.value
    dp.value = new_value
    dp.status = DataPointStatus.EDITED
    dp.rationale = note or dp.rationale

    audit.record(
        db,
        actor=actor,
        action="data_point.edited",
        entity_type="data_point",
        entity_id=dp.id,
        treaty_id=version.treaty_id,
        details={
            "version": version.version_number,
            "field_key": field_key,
            "old_value": old_value,
            "new_value": new_value,
            "note": note,
        },
    )
    db.commit()
    db.refresh(dp)
    return dp


def approve_version(db: Session, version: TreatyVersion, actor: str, note: str | None) -> TreatyVersion:
    _require_draft(version)
    previous = latest_approved_version(db, version.treaty_id)
    if previous is not None:
        previous.status = VersionStatus.SUPERSEDED
        audit.record(
            db,
            actor=actor,
            action="version.superseded",
            entity_type="treaty_version",
            entity_id=previous.id,
            treaty_id=version.treaty_id,
            details={"version": previous.version_number, "superseded_by": version.version_number},
        )

    version.status = VersionStatus.APPROVED
    version.reviewed_by = actor
    version.reviewed_at = utcnow()
    version.review_note = note
    audit.record(
        db,
        actor=actor,
        action="version.approved",
        entity_type="treaty_version",
        entity_id=version.id,
        treaty_id=version.treaty_id,
        details={"version": version.version_number, "note": note},
    )
    db.commit()
    db.refresh(version)
    return version


def reject_version(db: Session, version: TreatyVersion, actor: str, note: str | None) -> TreatyVersion:
    _require_draft(version)
    version.status = VersionStatus.REJECTED
    version.reviewed_by = actor
    version.reviewed_at = utcnow()
    version.review_note = note
    audit.record(
        db,
        actor=actor,
        action="version.rejected",
        entity_type="treaty_version",
        entity_id=version.id,
        treaty_id=version.treaty_id,
        details={"version": version.version_number, "note": note},
    )
    db.commit()
    db.refresh(version)
    return version


# --------------------------------------------------------------------------
# Amendments — always produce a NEW draft version
# --------------------------------------------------------------------------

def _base_version_for_amendment(db: Session, treaty: Treaty) -> TreatyVersion:
    base = latest_approved_version(db, treaty.id)
    if base is None:
        raise HTTPException(
            409,
            "This treaty has no approved version yet. Review and approve the current "
            "draft first (or edit the draft's data points directly).",
        )
    return base


def _copy_data_points(base: TreatyVersion, new_version: TreatyVersion, db: Session) -> dict[str, DataPoint]:
    copies: dict[str, DataPoint] = {}
    for dp in base.data_points:
        copy = DataPoint(
            version_id=new_version.id,
            field_key=dp.field_key,
            field_label=dp.field_label,
            value=dp.value,
            status=DataPointStatus.CARRIED_FORWARD,
            source_quote=dp.source_quote,
            source_location=dp.source_location,
            confidence=dp.confidence,
            rationale=dp.rationale,
        )
        db.add(copy)
        copies[dp.field_key] = copy
    return copies


def create_amendment_from_document(
    db: Session,
    treaty: Treaty,
    document: Document,
    amendment: AmendmentExtraction,
    actor: str,
) -> TreatyVersion:
    base = _base_version_for_amendment(db, treaty)
    version = TreatyVersion(
        treaty_id=treaty.id,
        version_number=_next_version_number(db, treaty.id),
        status=VersionStatus.DRAFT,
        origin=VersionOrigin.AMENDMENT_DOCUMENT,
        source_document_id=document.id,
        parent_version_id=base.id,
        change_summary=amendment.summary,
        effective_date=amendment.effective_date,
        created_by=actor,
    )
    db.add(version)
    db.flush()

    copies = _copy_data_points(base, version, db)
    applied = []
    for change in amendment.changes:
        dp = copies.get(change.field_key)
        if dp is None:
            continue
        dp.value = change.new_value
        dp.status = DataPointStatus.AMENDED_BY_DOCUMENT
        dp.source_quote = change.source_quote
        dp.source_location = change.source_location
        dp.confidence = change.confidence
        dp.rationale = change.rationale
        applied.append(change.field_key)

    audit.record(
        db,
        actor=actor,
        action="treaty.amendment_extracted",
        entity_type="treaty_version",
        entity_id=version.id,
        treaty_id=treaty.id,
        details={
            "document_id": document.id,
            "base_version": base.version_number,
            "new_version": version.version_number,
            "changed_fields": applied,
            "summary": amendment.summary,
            "effective_date": _date_text(amendment.effective_date),
        },
    )
    db.commit()
    db.refresh(version)
    return version


def create_manual_amendment(
    db: Session,
    treaty: Treaty,
    changes: dict,
    reason: str,
    effective_date: date | None,
    actor: str,
) -> TreatyVersion:
    unknown = sorted(set(changes) - FIELD_KEYS)
    if unknown:
        raise HTTPException(422, f"Unknown field keys: {unknown}. See GET /catalog for valid keys.")
    if not changes:
        raise HTTPException(422, "No changes supplied.")

    base = _base_version_for_amendment(db, treaty)
    version = TreatyVersion(
        treaty_id=treaty.id,
        version_number=_next_version_number(db, treaty.id),
        status=VersionStatus.DRAFT,
        origin=VersionOrigin.MANUAL_AMENDMENT,
        parent_version_id=base.id,
        change_summary=reason,
        effective_date=effective_date,
        created_by=actor,
    )
    db.add(version)
    db.flush()

    copies = _copy_data_points(base, version, db)
    old_values = {}
    for key, new_value in changes.items():
        dp = copies.get(key)
        if dp is None:
            # The base version predates this catalog field; add it fresh so the
            # amendment can still set it (rather than KeyError-ing out).
            dp = DataPoint(version_id=version.id, field_key=key, field_label=field_label(key))
            db.add(dp)
            copies[key] = dp
        old_values[key] = dp.value
        dp.value = new_value
        dp.status = DataPointStatus.AMENDED_MANUALLY
        dp.source_quote = None
        dp.source_location = None
        dp.confidence = 1.0
        dp.rationale = reason

    audit.record(
        db,
        actor=actor,
        action="treaty.amended_manually",
        entity_type="treaty_version",
        entity_id=version.id,
        treaty_id=treaty.id,
        details={
            "base_version": base.version_number,
            "new_version": version.version_number,
            "changes": {k: {"old": old_values[k], "new": v} for k, v in changes.items()},
            "reason": reason,
            "effective_date": _date_text(effective_date),
        },
    )
    db.commit()
    db.refresh(version)
    return version


# --------------------------------------------------------------------------
# Diff
# --------------------------------------------------------------------------

def diff_versions(version: TreatyVersion, parent: TreatyVersion | None) -> list[dict]:
    parent_values = {dp.field_key: dp.value for dp in parent.data_points} if parent else {}
    changes = []
    for dp in version.data_points:
        old = parent_values.get(dp.field_key)
        if old != dp.value:
            changes.append(
                {
                    "field_key": dp.field_key,
                    "field_label": dp.field_label,
                    "old_value": old,
                    "new_value": dp.value,
                    "status": dp.status,
                    "source_quote": dp.source_quote,
                    "rationale": dp.rationale,
                }
            )
    return changes
