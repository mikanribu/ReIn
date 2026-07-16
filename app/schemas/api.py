"""Request/response models for the HTTP API."""
from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.schemas.treaty_fields import FieldValue


# --- Documents -------------------------------------------------------------

class DocumentOut(BaseModel):
    id: str
    filename: str
    kind: str
    sha256: str
    uploaded_by: str
    created_at: datetime
    text_length: int
    # Populated in list views: the treaty this document produced/amended, if any.
    treaty_id: Optional[str] = None
    treaty_reference: Optional[str] = None

    model_config = {"from_attributes": True}


# --- Data points -----------------------------------------------------------

class DataPointOut(BaseModel):
    field_key: str
    field_label: str
    value: FieldValue
    status: str
    source_quote: Optional[str] = None
    source_location: Optional[str] = None
    confidence: Optional[float] = None
    rationale: Optional[str] = None
    updated_at: datetime

    model_config = {"from_attributes": True}


class DataPointEdit(BaseModel):
    value: FieldValue = None
    note: Optional[str] = Field(None, description="Why the value was changed (recorded in the audit trail).")
    actor: str = Field("user", description="Who is making the change.")


# --- Treaties / versions ----------------------------------------------------

class VersionSummary(BaseModel):
    id: str
    treaty_id: str
    version_number: int
    status: str
    origin: str
    source_document_id: Optional[str] = None
    parent_version_id: Optional[str] = None
    change_summary: Optional[str] = None
    effective_date: Optional[date] = None
    created_by: str
    created_at: datetime
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    review_note: Optional[str] = None

    model_config = {"from_attributes": True}


class ProductOut(BaseModel):
    id: str
    product_code: Optional[str] = None
    product_name: Optional[str] = None
    product_type: Optional[str] = None
    product_scope_status: Optional[str] = None
    source_quote: Optional[str] = None
    source_location: Optional[str] = None
    confidence: Optional[float] = None
    model_config = {"from_attributes": True}


class BenefitOut(BaseModel):
    id: str
    benefit_code: Optional[str] = None
    benefit_name: Optional[str] = None
    benefit_type: Optional[str] = None
    source_quote: Optional[str] = None
    source_location: Optional[str] = None
    confidence: Optional[float] = None
    model_config = {"from_attributes": True}


class CessionRuleOut(BaseModel):
    id: str
    country_code: Optional[str] = None
    cession_effective_start_date: Optional[str] = None
    cession_effective_end_date: Optional[str] = None
    policy_inception_start_date: Optional[str] = None
    policy_inception_end_date: Optional[str] = None
    cession_basis: Optional[str] = None
    layer_number: Optional[int] = None
    layer_name: Optional[str] = None
    cedant_retention_ratio: Optional[float] = None
    reinsurer_cession_ratio: Optional[float] = None
    layer_attachment_amount: Optional[float] = None
    layer_limit_amount: Optional[float] = None
    layer_detachment_amount: Optional[float] = None
    maximum_cedant_retention_amount: Optional[float] = None
    aggregation_basis: Optional[str] = None
    priority_order: Optional[int] = None
    source_quote: Optional[str] = None
    source_location: Optional[str] = None
    confidence: Optional[float] = None
    model_config = {"from_attributes": True}


class RateOut(BaseModel):
    id: str
    age_band: Optional[str] = None
    rate_class: Optional[str] = None
    rate_value: Optional[float] = None
    source_quote: Optional[str] = None
    source_location: Optional[str] = None
    confidence: Optional[float] = None
    model_config = {"from_attributes": True}


class VersionDetail(VersionSummary):
    data_points: list[DataPointOut]
    products: list[ProductOut] = []
    benefits: list[BenefitOut] = []
    cession_rules: list[CessionRuleOut] = []
    rates: list[RateOut] = []


class TreatyOut(BaseModel):
    id: str
    reference: str
    name: str
    created_at: datetime
    versions: list[VersionSummary] = []

    model_config = {"from_attributes": True}


class DiffEntry(BaseModel):
    field_key: str
    field_label: str
    old_value: FieldValue
    new_value: FieldValue
    status: str
    source_quote: Optional[str] = None
    rationale: Optional[str] = None


class VersionDiff(BaseModel):
    treaty_id: str
    from_version: Optional[int]
    to_version: int
    changes: list[DiffEntry]


# --- Actions ----------------------------------------------------------------

class ExtractRequest(BaseModel):
    document_id: str
    actor: str = "user"
    treaty_reference: Optional[str] = Field(
        None,
        description="Override the treaty reference; defaults to the extracted reference (or a generated one).",
    )


class ReviewRequest(BaseModel):
    actor: str = "user"
    note: Optional[str] = None


class DocumentAmendmentRequest(BaseModel):
    document_id: str
    actor: str = "user"


class ManualAmendmentRequest(BaseModel):
    changes: dict[str, FieldValue] = Field(
        ..., description="Mapping of field_key -> new value. Keys must belong to the field catalog."
    )
    reason: str = Field(..., description="Business reason for the amendment (audited).")
    effective_date: Optional[date] = None
    actor: str = "user"


# --- Child-collection editing (draft only) ---------------------------------

class ChildRowEdit(BaseModel):
    changes: dict[str, FieldValue] = Field(
        ..., description="Mapping of child field_key -> new value (only the fields to change)."
    )
    note: Optional[str] = Field(None, description="Why the row was changed (audited).")
    actor: str = "user"


class ChildRowCreate(BaseModel):
    values: dict[str, FieldValue] = Field(
        default_factory=dict, description="Field values for the new row (omitted keys default to null)."
    )
    note: Optional[str] = Field(None, description="Why the row was added (audited).")
    actor: str = "user"


class ChildRowDelete(BaseModel):
    note: Optional[str] = Field(None, description="Why the row was removed (audited).")
    actor: str = "user"


# --- Audit -------------------------------------------------------------------

class AuditEntryOut(BaseModel):
    id: int
    timestamp: datetime
    actor: str
    action: str
    entity_type: str
    entity_id: str
    treaty_id: Optional[str] = None
    details: Optional[dict] = None
    entry_hash: str
    prev_hash: str

    model_config = {"from_attributes": True}


class AuditVerification(BaseModel):
    valid: bool
    entries_checked: int
    first_broken_entry_id: Optional[int] = None


# --- Downstream consumption ---------------------------------------------------

class CurrentValuesOut(BaseModel):
    """Flat approved values for downstream calculation engines."""

    treaty_id: str
    reference: str
    name: str
    version_number: int
    approved_at: Optional[datetime]
    values: dict[str, FieldValue]
    products: list[ProductOut] = []
    benefits: list[BenefitOut] = []
    cession_rules: list[CessionRuleOut] = []
    rates: list[RateOut] = []


# --- Chat assistant -----------------------------------------------------------

class ChatMessage(BaseModel):
    role: Literal["user", "assistant"] = Field(..., description="'user' or 'assistant'.")
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(..., description="Conversation so far (oldest first).")
    treaty_id: Optional[str] = Field(
        None, description="If set, the assistant is grounded in this treaty's data."
    )


class ChatResponse(BaseModel):
    reply: str
    grounded_in_treaty: bool
    citations: list[str] = Field(
        default_factory=list,
        description="Treaty field labels the answer drew on (grounded replies only).",
    )


# --- Portfolio analytics (Knowledge Base) -------------------------------------

class AnalyticsBucket(BaseModel):
    value: str
    count: int


class AnalyticsBreakdown(BaseModel):
    key: str
    label: str
    buckets: list[AnalyticsBucket]


class CurrencyRow(BaseModel):
    currency: str
    count: int
    layer_limit_amount: float
    maximum_cedant_retention_amount: float


class PortfolioAnalytics(BaseModel):
    total_treaties: int
    breakdowns: list[AnalyticsBreakdown]
    by_currency: list[CurrencyRow]


class PortfolioSummary(BaseModel):
    summary: str


# --- Knowledge Base RAG -------------------------------------------------------

class KbAskRequest(BaseModel):
    question: str = Field(..., min_length=1)


class KbSource(BaseModel):
    treaty_id: str
    reference: str
    name: str


class KbAnswer(BaseModel):
    answer: str
    sources: list[KbSource] = Field(default_factory=list)


class KbIndexStatus(BaseModel):
    embedding_model: str
    indexed_chunks: int
    total_treaties: int
    ready: bool


class KbReindexResult(BaseModel):
    indexed_chunks: int


# --- Dashboard KPIs -----------------------------------------------------------

class StatsOut(BaseModel):
    """High-level counts for the home dashboard tiles."""

    treaties: int                # total treaties
    in_force: int                # treaties with an approved version
    awaiting_review: int         # draft versions pending approval
    amendments: int              # versions created by document or manual amendment
    approved_versions: int       # total approved versions
    documents: int               # documents uploaded
    audit_entries: int           # audit-trail entries
