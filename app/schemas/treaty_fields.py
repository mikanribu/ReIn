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
    ("lead_reinsurer_indicator", "Optional", CAT_TREATY,
     "Whether this reinsurer is the lead reinsurer in a panel (true/false)."),
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
    ("layer_number", "Mandatory", CAT_CESSION, "Layer identifier (number), e.g. 1, 2, 3."),
    ("layer_name", "Optional", CAT_CESSION, "Descriptive layer name, e.g. 'Base quota share layer'."),
    ("layer_1_ceding_ratio", "Mandatory where applicable", CAT_CESSION,
     "Reinsurer ceding percentage for layer 1 (number, %)."),
    ("layer_2_ceding_ratio", "Optional", CAT_CESSION, "Reinsurer ceding percentage for layer 2, if present (number, %)."),
    ("layer_3_ceding_ratio", "Optional", CAT_CESSION, "Reinsurer ceding percentage for layer 3, if present (number, %)."),
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
]

CATEGORY_ORDER = [CAT_TREATY, CAT_PRODUCT, CAT_CESSION]


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


# Build the extraction model from the catalogue so the two never diverge.
TreatyExtraction = create_model(
    "TreatyExtraction",
    __doc__="All defined data points to extract from a reinsurance treaty. "
            "Every field must be present in the output; use value=null when the "
            "treaty does not address the item.",
    **{key: (ExtractedField, Field(..., description=desc)) for key, _req, _cat, desc in _FIELDS},
)


# ---------------------------------------------------------------------------
# Catalogue accessors derived from _FIELDS
# ---------------------------------------------------------------------------

def field_label(key: str) -> str:
    """Human-readable label derived from the field key."""
    return key.replace("_", " ").title()


def field_catalog() -> dict[str, str]:
    """Mapping of field_key -> description (kept for backward compatibility)."""
    return {key: desc for key, _req, _cat, desc in _FIELDS}


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


FIELD_KEYS: frozenset[str] = frozenset(key for key, *_ in _FIELDS)


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
        ..., description="Every data point whose value changes. Empty if the document changes nothing in the catalogue."
    )
