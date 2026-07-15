"""Treaty lifecycle endpoints: extract, review, approve, amend, audit."""
import time

from fastapi import APIRouter, Depends, HTTPException
from langchain_core.language_models.chat_models import BaseChatModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import (
    AuditLog,
    Document,
    Treaty,
    TreatyVersion,
    VersionStatus,
)
from app.schemas.api import (
    AuditEntryOut,
    AuditVerification,
    ChildRowCreate,
    ChildRowDelete,
    ChildRowEdit,
    CurrentValuesOut,
    DataPointEdit,
    DataPointOut,
    DiffEntry,
    DocumentAmendmentRequest,
    ExtractRequest,
    ManualAmendmentRequest,
    ReviewRequest,
    StatsOut,
    TreatyOut,
    VersionDetail,
    VersionDiff,
)
from app.schemas.treaty_fields import field_catalog, field_metadata
from app.services import audit as audit_service
from app.services import extraction as extraction_service
from app.services import stats as stats_service
from app.services import treaties as treaty_service
from app.services.errors import translate_llm_errors
from app.services.llm import get_extraction_model
from app.config import get_settings
from app import observability

import time


router = APIRouter(tags=["treaties"])


def _get_document(db: Session, document_id: str, expected_kind: str) -> Document:
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(404, f"Document {document_id} not found")
    if doc.kind != expected_kind:
        raise HTTPException(422, f"Document {document_id} has kind '{doc.kind}', expected '{expected_kind}'")
    return doc


def _version_detail(version: TreatyVersion) -> VersionDetail:
    return VersionDetail.model_validate(version, from_attributes=True)


# --------------------------------------------------------------------------
# Catalog
# --------------------------------------------------------------------------

@router.get("/catalog")
def get_catalog() -> dict[str, str]:
    """The defined data-point catalog (field_key -> description)."""
    return field_catalog()


@router.get("/catalog/fields")
def get_catalog_fields() -> list[dict]:
    """The catalog with metadata: key, label, category, requirement, mandatory."""
    return field_metadata()


# --------------------------------------------------------------------------
# Dashboard stats
# --------------------------------------------------------------------------

@router.get("/stats", response_model=StatsOut)
def get_stats(db: Session = Depends(get_db)) -> StatsOut:
    """High-level KPIs for the home dashboard."""
    return stats_service.compute_stats(db)


# --------------------------------------------------------------------------
# Extraction
# --------------------------------------------------------------------------

@router.post("/extractions", response_model=VersionDetail, status_code=201)
def run_extraction(
    payload: ExtractRequest,
    db: Session = Depends(get_db),
    llm: BaseChatModel = Depends(get_extraction_model),
) -> VersionDetail:
    """Parse a treaty document into a new treaty with a draft version.

    The response contains every data point with its value, source quote,
    location, confidence and rationale — review it, correct any data point,
    then approve the version.
    """

    doc = _get_document(db, payload.document_id, "treaty")

    with observability.run(f"extract:{doc.filename}"):
        t0 = time.perf_counter()
        with translate_llm_errors("extract the treaty"):
            extraction = extraction_service.extract_treaty(llm, doc.content_text)
        version = treaty_service.create_treaty_from_extraction(
            db, doc, extraction, actor=payload.actor, reference_override=payload.treaty_reference
        )
        s = get_settings()
        model = {
            "anthropic": s.anthropic_model,
            "ollama": s.ollama_model,
            "azure_openai": s.azure_openai_deployment,
        }.get(s.extraction_llm_provider, s.extraction_llm_provider)
        observability.log_extraction(
            filename=doc.filename,
            provider=s.extraction_llm_provider,
            model=model,
            extraction=extraction,
            duration_s=time.perf_counter() - t0,
        )
        return _version_detail(version)


# --------------------------------------------------------------------------
# Treaties & versions
# --------------------------------------------------------------------------

@router.get("/treaties", response_model=list[TreatyOut])
def list_treaties(db: Session = Depends(get_db)) -> list[TreatyOut]:
    treaties = db.execute(select(Treaty).order_by(Treaty.created_at)).scalars().all()
    return [TreatyOut.model_validate(t, from_attributes=True) for t in treaties]


@router.get("/treaties/{treaty_id}", response_model=TreatyOut)
def get_treaty(treaty_id: str, db: Session = Depends(get_db)) -> TreatyOut:
    return TreatyOut.model_validate(treaty_service.get_treaty(db, treaty_id), from_attributes=True)


@router.get("/treaties/{treaty_id}/versions/{version_number}", response_model=VersionDetail)
def get_version(treaty_id: str, version_number: int, db: Session = Depends(get_db)) -> VersionDetail:
    return _version_detail(treaty_service.get_version(db, treaty_id, version_number))


@router.get("/treaties/{treaty_id}/versions/{version_number}/diff", response_model=VersionDiff)
def get_version_diff(treaty_id: str, version_number: int, db: Session = Depends(get_db)) -> VersionDiff:
    """Changes of this version relative to its parent (or to nothing for v1)."""
    version = treaty_service.get_version(db, treaty_id, version_number)
    parent = db.get(TreatyVersion, version.parent_version_id) if version.parent_version_id else None
    changes = treaty_service.diff_versions(version, parent)
    return VersionDiff(
        treaty_id=treaty_id,
        from_version=parent.version_number if parent else None,
        to_version=version.version_number,
        changes=[DiffEntry(**c) for c in changes],
    )


# --------------------------------------------------------------------------
# Review: edit / approve / reject
# --------------------------------------------------------------------------

@router.patch(
    "/treaties/{treaty_id}/versions/{version_number}/data-points/{field_key}",
    response_model=DataPointOut,
)
def edit_data_point(
    treaty_id: str,
    version_number: int,
    field_key: str,
    payload: DataPointEdit,
    db: Session = Depends(get_db),
) -> DataPointOut:
    """Correct a data point on a draft version (audited)."""
    version = treaty_service.get_version(db, treaty_id, version_number)
    dp = treaty_service.edit_data_point(db, version, field_key, payload.value, payload.actor, payload.note)
    return DataPointOut.model_validate(dp, from_attributes=True)


# --------------------------------------------------------------------------
# Review: edit child collections (products / benefits / cession rules) on drafts
# --------------------------------------------------------------------------

@router.post("/treaties/{treaty_id}/versions/{version_number}/children/{collection}")
def add_child_row(
    treaty_id: str,
    version_number: int,
    collection: str,
    payload: ChildRowCreate,
    db: Session = Depends(get_db),
) -> dict:
    """Add a row to a child collection of a draft version (audited)."""
    version = treaty_service.get_version(db, treaty_id, version_number)
    return treaty_service.add_child_row(db, version, collection, payload.values, payload.actor, payload.note)


@router.patch("/treaties/{treaty_id}/versions/{version_number}/children/{collection}/{row_id}")
def edit_child_row(
    treaty_id: str,
    version_number: int,
    collection: str,
    row_id: str,
    payload: ChildRowEdit,
    db: Session = Depends(get_db),
) -> dict:
    """Edit fields of one child row on a draft version (audited)."""
    version = treaty_service.get_version(db, treaty_id, version_number)
    return treaty_service.edit_child_row(db, version, collection, row_id, payload.changes, payload.actor, payload.note)


@router.delete("/treaties/{treaty_id}/versions/{version_number}/children/{collection}/{row_id}")
def delete_child_row(
    treaty_id: str,
    version_number: int,
    collection: str,
    row_id: str,
    payload: ChildRowDelete = ChildRowDelete(),
    db: Session = Depends(get_db),
) -> dict:
    """Remove one child row from a draft version (audited)."""
    version = treaty_service.get_version(db, treaty_id, version_number)
    treaty_service.delete_child_row(db, version, collection, row_id, payload.actor, payload.note)
    return {"deleted": row_id}


@router.post("/treaties/{treaty_id}/versions/{version_number}/approve", response_model=VersionDetail)
def approve_version(
    treaty_id: str, version_number: int, payload: ReviewRequest, db: Session = Depends(get_db)
) -> VersionDetail:
    version = treaty_service.get_version(db, treaty_id, version_number)
    return _version_detail(treaty_service.approve_version(db, version, payload.actor, payload.note))


@router.post("/treaties/{treaty_id}/versions/{version_number}/reject", response_model=VersionDetail)
def reject_version(
    treaty_id: str, version_number: int, payload: ReviewRequest, db: Session = Depends(get_db)
) -> VersionDetail:
    version = treaty_service.get_version(db, treaty_id, version_number)
    return _version_detail(treaty_service.reject_version(db, version, payload.actor, payload.note))


# --------------------------------------------------------------------------
# Amendments
# --------------------------------------------------------------------------

@router.post("/treaties/{treaty_id}/amendments/from-document", response_model=VersionDetail, status_code=201)
def amend_from_document(
    treaty_id: str,
    payload: DocumentAmendmentRequest,
    db: Session = Depends(get_db),
    llm: BaseChatModel = Depends(get_extraction_model),
) -> VersionDetail:
    """Parse an adjustment/endorsement document and create a new draft version
    with the changed data points flagged for review."""
    treaty = treaty_service.get_treaty(db, treaty_id)
    doc = _get_document(db, payload.document_id, "amendment")
    base = treaty_service.latest_approved_version(db, treaty_id)
    if base is None:
        raise HTTPException(409, "This treaty has no approved version to amend yet.")
    with translate_llm_errors("parse the amendment"):
        amendment = extraction_service.extract_amendment(
            llm, doc.content_text, treaty_service.values_dict(base)
        )
    version = treaty_service.create_amendment_from_document(db, treaty, doc, amendment, payload.actor)
    return _version_detail(version)


@router.post("/treaties/{treaty_id}/amendments/manual", response_model=VersionDetail, status_code=201)
def amend_manually(
    treaty_id: str,
    payload: ManualAmendmentRequest,
    db: Session = Depends(get_db),
) -> VersionDetail:
    """Create a new draft version with user-supplied changes."""
    treaty = treaty_service.get_treaty(db, treaty_id)
    version = treaty_service.create_manual_amendment(
        db, treaty, payload.changes, payload.reason, payload.effective_date, payload.actor
    )
    return _version_detail(version)


# --------------------------------------------------------------------------
# Downstream consumption
# --------------------------------------------------------------------------

@router.get("/treaties/{treaty_id}/current", response_model=CurrentValuesOut)
def get_current_values(treaty_id: str, db: Session = Depends(get_db)) -> CurrentValuesOut:
    """Flat, approved data-point values for downstream calculation engines.

    Only approved versions are ever served here — drafts and rejected
    versions can never leak into calculations.
    """
    treaty = treaty_service.get_treaty(db, treaty_id)
    version = treaty_service.latest_approved_version(db, treaty_id)
    if version is None:
        raise HTTPException(404, "This treaty has no approved version yet.")
    children = treaty_service.children_dict(version)
    return CurrentValuesOut(
        treaty_id=treaty.id,
        reference=treaty.reference,
        name=treaty.name,
        version_number=version.version_number,
        approved_at=version.reviewed_at,
        values=treaty_service.values_dict(version),
        **children,
    )


# --------------------------------------------------------------------------
# Audit
# --------------------------------------------------------------------------

@router.get("/treaties/{treaty_id}/audit", response_model=list[AuditEntryOut])
def get_treaty_audit(treaty_id: str, db: Session = Depends(get_db)) -> list[AuditEntryOut]:
    treaty_service.get_treaty(db, treaty_id)
    entries = db.execute(
        select(AuditLog).where(AuditLog.treaty_id == treaty_id).order_by(AuditLog.id)
    ).scalars().all()
    return [AuditEntryOut.model_validate(e, from_attributes=True) for e in entries]


@router.get("/audit", response_model=list[AuditEntryOut])
def get_full_audit(db: Session = Depends(get_db)) -> list[AuditEntryOut]:
    entries = db.execute(select(AuditLog).order_by(AuditLog.id)).scalars().all()
    return [AuditEntryOut.model_validate(e, from_attributes=True) for e in entries]


@router.get("/audit/verify", response_model=AuditVerification)
def verify_audit(db: Session = Depends(get_db)) -> AuditVerification:
    """Re-walk the audit hash chain to prove the trail has not been tampered with."""
    valid, checked, broken = audit_service.verify_chain(db)
    return AuditVerification(valid=valid, entries_checked=checked, first_broken_entry_id=broken)
