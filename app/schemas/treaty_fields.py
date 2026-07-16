"""The defined data-point catalogue for reinsurance treaties.

The catalogue is metadata-driven: ``_FIELDS`` is the single source of truth,
listing every extracted data point with its **category**, whether it is
**mandatory or optional**, and a description. The Pydantic extraction model,
the field catalogue endpoint, edit/amendment validation and the database rows
are all derived from it, so they can never drift.

Each field is wrapped in ``ExtractedField`` so the LLM must return not only the
value but also the exact source quote, its location, a confidence score and a
short rationale — this is what makes the extraction transparent and reviewable.

Note: internal system identifiers (treaty_id, product_id, benefit_id,
cession_rule_id) are assigned by the system, not extracted from the document,
so they are not part of this extraction catalogue.
"""
from datetime import date
from typing import Optional, Union

from pydantic import BaseModel, Field, create_model

# JSON-friendly value union kept deliberately simple so it survives
# structured-output schema restrictions and database JSON storage.
FieldValue = Optional[Union[str, float, int, bool, list[str]]]

# Category labels used to group the catalogue.
CAT_TREATY = "Treaty"
CAT_PRODUCT = "Product & Benefit"
CAT_CESSION = "Cession & Layers"
CAT_RATE = "Reinsurance Premium Rate"

# (field_key, requirement, category, description)
# ``requirement`` keeps the exact wording (incl. "Mandatory where applicable"
# etc.); ``mandatory`` is derived from it below.
_FIELDS: list[tuple[str, str, str, str]] = [
    # --- Treaty -------------------------------------------------------------
    ("treaty_code", "Optional", CAT_TREATY,
     "Treaty reference stated in the contract, e.g. PHL-CGR-QS-2027-01. Optional: some scanned/legacy treaties lack a formal code."),
    ("treaty_name", "Mandatory", CAT_TREATY,
     "Name/title of the treaty, e.g. 'Quota Share Life Reinsurance Agreement'."),
    ("treaty_type", "Mandatory", CAT_TREATY,
     "Type of arrangement, e.g. quota_share, surplus, excess_of_loss, coinsurance, yrt, stop_loss."),
    ("reinsurance_basis", "Mandatory", CAT_TREATY,
     "automatic, facultative, automatic_and_facultative, obligatory, or retrocession."),
    ("cedant_name", "Mandatory", CAT_TREATY, "Legal name of the ceding company."),
    ("reinsurer_name", "Mandatory", CAT_TREATY, "Legal name of the reinsurer."),
    ("party_share_percentage", "Optional", CAT_TREATY,
     "Reinsurer participation share (number, %) if multiple reinsurers participate."),
    ("treaty_effective_start_date", "Mandatory", CAT_TREATY,
     "Date the treaty becomes effective (ISO date YYYY-MM-DD)."),
    ("treaty_effective_end_date", "Mandatory", CAT_TREATY,
     "Date the treaty ends (ISO date). Use null if open-ended/continuous."),
    ("new_business_start_date", "Mandatory", CAT_TREATY,
     "Date from which newly incepted policies can be ceded (ISO date). Often equals the effective start date."),
    ("new_business_end_date", "Optional", CAT_TREATY,
     "Date after which no new business may be ceded (ISO date)."),
    ("contract_currency_code", "Mandatory", CAT_TREATY,
     "Currency for treaty limits, premiums and settlement (ISO code, e.g. USD)."),
    ("settlement_currency_code", "Mandatory", CAT_TREATY,
     "Currency in which reinsurance balances are settled (ISO code)."),
    ("premium_rate", "Optional", CAT_TREATY,
     "Headline flat reinsurance premium rate (number) for treaties that quote a single rate. "
     "Leave null when the treaty provides a rate table instead (captured in the rate table)."),

    # --- Product & Benefit --------------------------------------------------
    ("product_code", "Mandatory", CAT_PRODUCT, "Source or treaty product code, where available."),
    ("product_name", "Mandatory", CAT_PRODUCT, "Product covered by the treaty."),
    ("product_type", "Mandatory", CAT_PRODUCT,
     "Product category, e.g. term_life, whole_life, universal_life, family_income, mortgage_protection."),
    ("product_scope_status", "Mandatory", CAT_PRODUCT,
     "Whether the product is included, excluded, partially_included, or subject_to_endorsement."),
    ("benefit_code", "Mandatory", CAT_PRODUCT, "Source or treaty benefit code, where available."),
    ("benefit_name", "Mandatory", CAT_PRODUCT,
     "Benefit name, e.g. death benefit, terminal illness, waiver, family income."),
    ("benefit_type", "Mandatory", CAT_PRODUCT,
     "Type of benefit: death, terminal_illness, accidental_death, income_benefit, waiver, rider."),

    # --- Cession & Layers ---------------------------------------------------
    # Layers are pre-flattened to 1-3 columns; store the cession rule at treaty level.
    ("country_code", "Mandatory", CAT_CESSION, "Country/jurisdiction the cession rule applies to (ISO code)."),
    ("cession_effective_start_date", "Mandatory", CAT_CESSION, "Effective date of the cession rule (ISO date)."),
    ("cession_effective_end_date", "Optional", CAT_CESSION, "End date of the cession rule (ISO date)."),
    ("policy_inception_start_date", "Mandatory", CAT_CESSION,
     "Policy inception cohort start date for the cession rule (ISO date)."),
    ("policy_inception_end_date", "Optional", CAT_CESSION,
     "Policy inception cohort end date for the cession rule (ISO date)."),
    ("cession_basis", "Mandatory", CAT_CESSION,
     "quota_share, surplus, layered_quota_share, excess, modified_coinsurance, etc."),
    ("layer_number", "Mandatory", CAT_CESSION, "Layer identifier (number); one cession-rule row per layer, e.g. 1, 2, 3."),
    ("layer_name", "Optional", CAT_CESSION, "Descriptive layer name, e.g. 'Base quota share layer'."),
    ("cedant_retention_ratio", "Mandatory", CAT_CESSION, "Percentage retained by the cedant under the rule/layer (number, %)."),
    ("reinsurer_cession_ratio", "Mandatory", CAT_CESSION, "Percentage ceded to the reinsurer under the rule/layer (number, %)."),
    ("layer_attachment_amount", "Mandatory for layered/surplus", CAT_CESSION, "Amount at which the layer begins."),
    ("layer_limit_amount", "Mandatory for layered/surplus", CAT_CESSION, "Maximum amount covered by the layer."),
    ("layer_detachment_amount", "Optional", CAT_CESSION, "Amount at which the layer ends."),
    ("maximum_cedant_retention_amount", "Mandatory", CAT_CESSION,
     "Maximum retention retained by the cedant, e.g. 1000000."),
    ("aggregation_basis", "Mandatory", CAT_CESSION,
     "per_life, per_policy, per_benefit, per_claim, across_policies, or across_benefits."),
    ("priority_order", "Mandatory", CAT_CESSION, "Rule priority (number) where multiple rules overlap."),

    # --- Reinsurance Premium Rate (tidy rate table: one row per cell) --------
    # A rate table has an age/age-band row axis and several rate-class columns
    # whose names vary by treaty. It is stored in long/tidy form — one row per
    # cell — so any set of columns and any length is captured verbatim.
    ("age_band", "Mandatory", CAT_RATE,
     "Age or age band the rate applies to, exactly as written, e.g. '18-29', '45', or '65+'."),
    ("rate_class", "Mandatory", CAT_RATE,
     "The rate-class / column heading exactly as written, e.g. 'Preferred NS', 'Standard NS', "
     "'Standard Smoker', 'Substandard Table B'."),
    ("rate_value", "Mandatory", CAT_RATE,
     "The numeric reinsurance rate in that cell (number), exactly as written, e.g. 0.72."),
]

CATEGORY_ORDER = [CAT_TREATY, CAT_PRODUCT, CAT_CESSION, CAT_RATE]


class ExtractedField(BaseModel):
    """One extracted data point with full provenance."""

    value: FieldValue = Field(
        None,
        description=(
            "The extracted value. Use null if the treaty does not specify it. "
            "Use numbers for amounts/percentages (percentage as a number, e.g. 25 for 25%), "
            "ISO dates (YYYY-MM-DD) for dates, true/false for indicators, and lists of strings for enumerations."
        ),
    )
    source_quote: Optional[str] = Field(
        None,
        description="Exact verbatim quote from the document that supports this value (max ~300 chars).",
    )
    source_location: Optional[str] = Field(
        None,
        description="Where the quote is found, e.g. 'Article 5 — Premium' or 'page 3, Retention clause'.",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence that the value is correct, 0.0-1.0. Use 0.0 when the value is null.",
    )
    rationale: Optional[str] = Field(
        None,
        description="One short sentence explaining how the value was derived, especially if interpreted.",
    )


# ---------------------------------------------------------------------------
# Split the catalogue into the flat, treaty-level fields (stored as DataPoints)
# and the child collections (products / benefits / cession rules), which are
# stored as one-to-many rows per treaty version.
# ---------------------------------------------------------------------------
_TREATY_FIELDS = [f for f in _FIELDS if f[2] == CAT_TREATY]
_PRODUCT_FIELDS = [f for f in _FIELDS if f[2] == CAT_PRODUCT and f[0].startswith("product_")]
_BENEFIT_FIELDS = [f for f in _FIELDS if f[2] == CAT_PRODUCT and f[0].startswith("benefit_")]
_CESSION_FIELDS = [f for f in _FIELDS if f[2] == CAT_CESSION]
_RATE_FIELDS = [f for f in _FIELDS if f[2] == CAT_RATE]

# Field keys that need a non-string Python type in the child models.
_INT_KEYS = {"layer_number", "priority_order"}
_FLOAT_KEYS = {
    "cedant_retention_ratio", "reinsurer_cession_ratio", "layer_attachment_amount",
    "layer_limit_amount", "layer_detachment_amount", "maximum_cedant_retention_amount",
    "rate_value",
}


def _child_type(key: str):
    if key in _INT_KEYS:
        return Optional[int]
    if key in _FLOAT_KEYS:
        return Optional[float]
    return Optional[str]


# Record-level provenance for a child row (one set per row, not per field).
_PROVENANCE = {
    "source_quote": (Optional[str], Field(None, description="Exact supporting quote from the document.")),
    "source_location": (Optional[str], Field(None, description="Where in the document the row is stated.")),
    "confidence": (float, Field(0.0, ge=0.0, le=1.0, description="Confidence this row is correct, 0-1.")),
}


def _child_model(name: str, fields: list) -> type[BaseModel]:
    spec = {key: (_child_type(key), Field(None, description=desc)) for key, _r, _c, desc in fields}
    spec.update(_PROVENANCE)
    return create_model(name, **spec)


ProductExtraction = _child_model("ProductExtraction", _PRODUCT_FIELDS)
BenefitExtraction = _child_model("BenefitExtraction", _BENEFIT_FIELDS)
CessionRuleExtraction = _child_model("CessionRuleExtraction", _CESSION_FIELDS)
RateExtraction = _child_model("RateExtraction", _RATE_FIELDS)

# The treaty-level flat fields (ExtractedField each) + the child collections.
TreatyExtraction = create_model(
    "TreatyExtraction",
    __doc__="Data extracted from a reinsurance treaty: treaty-level fields (each "
            "with provenance), plus lists of products, benefits, cession rules "
            "(one row per layer) and premium-rate-table cells (one row per "
            "age-band × rate-class cell). Use null / empty lists when absent.",
    **{key: (ExtractedField, Field(..., description=desc)) for key, _req, _cat, desc in _TREATY_FIELDS},
    products=(list[ProductExtraction], Field(default_factory=list, description="Products in scope.")),
    benefits=(list[BenefitExtraction], Field(default_factory=list, description="Benefits in scope.")),
    cession_rules=(list[CessionRuleExtraction], Field(default_factory=list, description="Cession rules / layers.")),
    rates=(list[RateExtraction], Field(
        default_factory=list,
        description="Every cell of the reinsurance premium rate table: one entry per "
                    "(age band × rate class). Capture the column heading verbatim as "
                    "rate_class. Empty list if the treaty has no rate table.")),
)

# Field-key lists per collection (used by storage to copy the right columns).
PRODUCT_KEYS = [f[0] for f in _PRODUCT_FIELDS]
BENEFIT_KEYS = [f[0] for f in _BENEFIT_FIELDS]
CESSION_KEYS = [f[0] for f in _CESSION_FIELDS]
RATE_KEYS = [f[0] for f in _RATE_FIELDS]


def coerce_child_value(key: str, value):
    """Coerce a raw (JSON/string) value to the Python type a child column
    expects. Empty/blank -> None. Raises ValueError on a bad number so callers
    can surface a clean validation error."""
    if value is None or (isinstance(value, str) and value.strip() == ""):
        return None
    if key in _INT_KEYS:
        return int(float(value)) if isinstance(value, str) else int(value)
    if key in _FLOAT_KEYS:
        return float(value)
    return str(value)


# ---------------------------------------------------------------------------
# Catalogue accessors derived from _FIELDS
# ---------------------------------------------------------------------------

def field_label(key: str) -> str:
    """Human-readable label derived from the field key."""
    return key.replace("_", " ").title()


def field_catalog() -> dict[str, str]:
    """Treaty-level field_key -> description (the flat data points).

    Children live in their own collections, not the flat catalog."""
    return {key: desc for key, _req, _cat, desc in _TREATY_FIELDS}


def field_metadata() -> list[dict]:
    """Full per-field metadata: key, label, category, requirement, mandatory, description."""
    return [
        {
            "key": key,
            "label": field_label(key),
            "category": cat,
            "requirement": req,
            "mandatory": req.startswith("Mandatory"),
            "description": desc,
        }
        for key, req, cat, desc in _FIELDS
    ]


# Only treaty-level (flat) fields can be edited/amended by key; children are
# replaced wholesale (MVP) rather than addressed individually.
FIELD_KEYS: frozenset[str] = frozenset(f[0] for f in _TREATY_FIELDS)


# ---------------------------------------------------------------------------
# Amendment extraction schema
# ---------------------------------------------------------------------------

class AmendedField(BaseModel):
    """One data point changed by an amendment/endorsement document."""

    field_key: str = Field(
        ...,
        description=f"The data point being amended. Must be one of: {', '.join(sorted(FIELD_KEYS))}.",
    )
    new_value: FieldValue = Field(
        None, description="The new value after the amendment (same conventions as extraction values)."
    )
    source_quote: Optional[str] = Field(
        None, description="Exact quote from the amendment document supporting the change."
    )
    source_location: Optional[str] = Field(None, description="Where in the amendment document the change is stated.")
    confidence: float = Field(..., ge=0.0, le=1.0)
    rationale: Optional[str] = Field(None, description="Short explanation of the change.")


class AmendmentExtraction(BaseModel):
    """Changes described by a treaty adjustment/endorsement document,
    mapped against the defined data-point catalogue."""

    summary: str = Field(..., description="One-paragraph summary of what the amendment changes.")
    effective_date: Optional[date] = Field(
        None, description="Date the amendment takes effect (ISO date), if stated."
    )
    changes: list[AmendedField] = Field(
        ..., description="Every treaty-level data point whose value changes. Empty if none change."
    )
    # Child collections: when the amendment changes the products/benefits/cession
    # rules, return the COMPLETE new list and it replaces the previous one
    # wholesale. Leave as null to carry the existing rows forward unchanged.
    products: Optional[list[ProductExtraction]] = Field(
        None, description="If the products in scope change, the full new list; else null."
    )
    benefits: Optional[list[BenefitExtraction]] = Field(
        None, description="If the benefits in scope change, the full new list; else null."
    )
    cession_rules: Optional[list[CessionRuleExtraction]] = Field(
        None, description="If the cession rules / layers change, the full new list; else null."
    )
    rates: Optional[list[RateExtraction]] = Field(
        None, description="If the premium rate table changes, the full new list of cells; else null."
    )
