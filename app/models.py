"""SQLAlchemy ORM models.

Design principles
-----------------
* **Immutability where it matters** — a treaty version is frozen once it is
  approved or rejected; changes after that point always create a *new*
  version, so the full history is preserved.
* **Transparency** — every data point stores the exact quote from the source
  document, its location, a confidence score, and the model's rationale, so
  a reviewer can verify each value before approving.
* **Traceability** — every state change is recorded in an append-only,
  hash-chained audit log.
"""
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import JSON, Date, Float, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class VersionStatus:
    DRAFT = "draft"          # extracted / amended, awaiting human review
    APPROVED = "approved"    # reviewed and confirmed — usable downstream
    REJECTED = "rejected"    # reviewed and refused
    SUPERSEDED = "superseded"  # was approved, replaced by a newer approved version


class VersionOrigin:
    EXTRACTION = "extraction"                  # initial parse of a treaty document
    AMENDMENT_DOCUMENT = "amendment_document"  # parsed from an adjustment/endorsement document
    MANUAL_AMENDMENT = "manual_amendment"      # changes entered by a user


class DataPointStatus:
    EXTRACTED = "extracted"              # value came from the LLM extraction
    NOT_FOUND = "not_found"              # extraction could not locate the field
    EDITED = "edited"                    # manually corrected while in draft
    CARRIED_FORWARD = "carried_forward"  # unchanged copy from the parent version
    AMENDED_BY_DOCUMENT = "amended_by_document"
    AMENDED_MANUALLY = "amended_manually"


class Document(Base):
    """An uploaded source document (treaty wording or amendment/endorsement)."""

    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    filename: Mapped[str] = mapped_column(String(512))
    kind: Mapped[str] = mapped_column(String(32))  # 'treaty' | 'amendment'
    content_text: Mapped[str] = mapped_column(Text)
    # Original uploaded bytes + MIME type, so the source document can be
    # viewed/downloaded in the UI (nullable: docs uploaded before this was
    # added, or very large files, may not carry the raw bytes).
    content_bytes: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    uploaded_by: Mapped[str] = mapped_column(String(256), default="system")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Treaty(Base):
    """The logical treaty. Actual content lives in versions."""

    __tablename__ = "treaties"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    reference: Mapped[str] = mapped_column(String(256), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    versions: Mapped[list["TreatyVersion"]] = relationship(
        back_populates="treaty", order_by="TreatyVersion.version_number"
    )


class TreatyVersion(Base):
    """One immutable snapshot of a treaty's data points."""

    __tablename__ = "treaty_versions"
    __table_args__ = (UniqueConstraint("treaty_id", "version_number"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    treaty_id: Mapped[str] = mapped_column(ForeignKey("treaties.id"), index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default=VersionStatus.DRAFT)
    origin: Mapped[str] = mapped_column(String(32))
    source_document_id: Mapped[str | None] = mapped_column(ForeignKey("documents.id"), nullable=True)
    parent_version_id: Mapped[str | None] = mapped_column(ForeignKey("treaty_versions.id"), nullable=True)
    change_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    created_by: Mapped[str] = mapped_column(String(256), default="system")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    reviewed_by: Mapped[str | None] = mapped_column(String(256), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    treaty: Mapped[Treaty] = relationship(back_populates="versions")
    source_document: Mapped[Document | None] = relationship()
    data_points: Mapped[list["DataPoint"]] = relationship(
        back_populates="version", order_by="DataPoint.field_key", cascade="all, delete-orphan"
    )
    products: Mapped[list["TreatyProduct"]] = relationship(
        back_populates="version", order_by="TreatyProduct.seq", cascade="all, delete-orphan"
    )
    benefits: Mapped[list["TreatyBenefit"]] = relationship(
        back_populates="version", order_by="TreatyBenefit.seq", cascade="all, delete-orphan"
    )
    cession_rules: Mapped[list["CessionRule"]] = relationship(
        back_populates="version", order_by="CessionRule.seq", cascade="all, delete-orphan"
    )

    @property
    def is_editable(self) -> bool:
        return self.status == VersionStatus.DRAFT


class DataPoint(Base):
    """A single mapped field of a treaty version, with full provenance."""

    __tablename__ = "data_points"
    __table_args__ = (UniqueConstraint("version_id", "field_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    version_id: Mapped[str] = mapped_column(ForeignKey("treaty_versions.id"), index=True)
    field_key: Mapped[str] = mapped_column(String(128), index=True)
    field_label: Mapped[str] = mapped_column(String(256))
    # Values are stored as JSON so numbers, strings, booleans and lists are
    # all preserved with their type for downstream calculations.
    value: Mapped[dict | list | str | float | int | bool | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default=DataPointStatus.EXTRACTED)

    # Provenance / transparency
    source_quote: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_location: Mapped[str | None] = mapped_column(String(512), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)

    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    version: Mapped[TreatyVersion] = relationship(back_populates="data_points")


class _ChildProvenance:
    """Mixin: record-level provenance for a child row (one set per row, rather
    than per field). ``seq`` preserves the order the model returned them in."""

    seq: Mapped[int] = mapped_column(Integer, default=0)
    source_quote: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_location: Mapped[str | None] = mapped_column(String(512), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)


class TreatyProduct(Base, _ChildProvenance):
    """A product in scope for a treaty version (flat list; one row per product)."""

    __tablename__ = "treaty_products"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    version_id: Mapped[str] = mapped_column(ForeignKey("treaty_versions.id"), index=True)
    product_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    product_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    product_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    product_scope_status: Mapped[str | None] = mapped_column(String(64), nullable=True)

    version: Mapped[TreatyVersion] = relationship(back_populates="products")


class TreatyBenefit(Base, _ChildProvenance):
    """A benefit in scope for a treaty version (flat list; one row per benefit)."""

    __tablename__ = "treaty_benefits"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    version_id: Mapped[str] = mapped_column(ForeignKey("treaty_versions.id"), index=True)
    benefit_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    benefit_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    benefit_type: Mapped[str | None] = mapped_column(String(128), nullable=True)

    version: Mapped[TreatyVersion] = relationship(back_populates="benefits")


class CessionRule(Base, _ChildProvenance):
    """A cession rule / layer for a treaty version (one row per layer)."""

    __tablename__ = "cession_rules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    version_id: Mapped[str] = mapped_column(ForeignKey("treaty_versions.id"), index=True)
    country_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    cession_effective_start_date: Mapped[str | None] = mapped_column(String(32), nullable=True)
    cession_effective_end_date: Mapped[str | None] = mapped_column(String(32), nullable=True)
    policy_inception_start_date: Mapped[str | None] = mapped_column(String(32), nullable=True)
    policy_inception_end_date: Mapped[str | None] = mapped_column(String(32), nullable=True)
    cession_basis: Mapped[str | None] = mapped_column(String(64), nullable=True)
    layer_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    layer_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    cedant_retention_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    reinsurer_cession_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    layer_attachment_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    layer_limit_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    layer_detachment_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    maximum_cedant_retention_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    aggregation_basis: Mapped[str | None] = mapped_column(String(64), nullable=True)
    priority_order: Mapped[int | None] = mapped_column(Integer, nullable=True)

    version: Mapped[TreatyVersion] = relationship(back_populates="cession_rules")


class TreatyChunk(Base):
    """A retrievable text chunk for the Knowledge Base semantic index.

    Each chunk is a compact, human-readable rendering of one treaty (its key
    data points) plus its embedding vector. Stored as JSON so it works on both
    SQLite (dev) and Postgres; a pgvector column is the production optimization.
    The ``embedding_model`` tag lets retrieval ignore vectors produced by a
    different model, so switching providers just means reindexing.
    """

    __tablename__ = "treaty_chunks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    treaty_id: Mapped[str] = mapped_column(ForeignKey("treaties.id"), index=True)
    treaty_reference: Mapped[str] = mapped_column(String(256))
    treaty_name: Mapped[str] = mapped_column(String(512))
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list] = mapped_column(JSON)
    embedding_model: Mapped[str] = mapped_column(String(128), index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class AuditLog(Base):
    """Append-only audit trail. Entries are hash-chained: each entry's hash
    covers the previous entry's hash, so any tampering with history breaks
    the chain and is detectable via the verification endpoint."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(default=utcnow)
    actor: Mapped[str] = mapped_column(String(256))
    action: Mapped[str] = mapped_column(String(64))
    entity_type: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[str] = mapped_column(String(36))
    treaty_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    prev_hash: Mapped[str] = mapped_column(String(64))
    entry_hash: Mapped[str] = mapped_column(String(64))
