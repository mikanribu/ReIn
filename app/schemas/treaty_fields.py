"""The defined data-point catalog for reinsurance treaties.

This module is the single place to maintain when the set of extracted data
points changes: add/remove a field on ``TreatyExtraction`` and everything
else (LLM structured output, field catalog endpoint, validation of manual
edits, database rows) follows automatically.

Each field is wrapped in ``ExtractedField`` so the LLM must return not only
the value but also the exact source quote, its location in the document, a
confidence score and a short rationale — this is what makes the extraction
transparent and reviewable.
"""
from datetime import date
from typing import Optional, Union

from pydantic import BaseModel, Field

# JSON-friendly value union kept deliberately simple so it survives
# structured-output schema restrictions and database JSON storage.
FieldValue = Optional[Union[str, float, int, bool, list[str]]]


class ExtractedField(BaseModel):
    """One extracted data point with full provenance."""

    value: FieldValue = Field(
        None,
        description=(
            "The extracted value. Use null if the treaty does not specify it. "
            "Use numbers for amounts/percentages (percentage as a number, e.g. 25 for 25%), "
            "ISO dates (YYYY-MM-DD) for dates, and lists of strings for enumerations."
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


class TreatyExtraction(BaseModel):
    """All defined data points to extract from a reinsurance treaty.

    Every field must be present in the output; use value=null when the
    treaty does not address the item.
    """

    # --- Identification ---
    treaty_name: ExtractedField = Field(..., description="Full name/title of the treaty.")
    treaty_reference: ExtractedField = Field(..., description="Contract/treaty reference number or unique identifier.")
    treaty_type: ExtractedField = Field(
        ...,
        description=(
            "Type of treaty. One of: 'quota_share', 'surplus', 'per_risk_xl', "
            "'per_event_xl', 'cat_xl', 'stop_loss', 'facultative_obligatory', 'other'."
        ),
    )
    #form: ExtractedField = Field(..., description="'proportional' or 'non_proportional'.")

    # -- Reinsurance Treaty Details ---
    treaty_addendum_number: ExtractedField = Field(..., description="Unique identifier of the treaty addendum, if any.")
    treaty_amendment_number: ExtractedField = Field(..., description="Unique identifier of the treaty amendment, if any.")
    
    # --- Parties ---
    treaty_company_identifier: ExtractedField = Field(..., description="Name of the ceding company (the reinsured).")
    reinsurers: ExtractedField = Field(
        ..., description="List of reinsurer names with their share percentage if stated, e.g. ['Re A (60%)', 'Re B (40%)']."
    )
    broker: ExtractedField = Field(..., description="Intermediary/broker name, if any.")

    # --- Period & scope ---
    inception_date: ExtractedField = Field(..., description="Inception date of the period of coverage (ISO date).")
    expiry_date: ExtractedField = Field(..., description="Expiry date, or 'continuous' if the treaty is continuous.")

    #territory: ExtractedField = Field(..., description="Territorial scope of the treaty.")
    #lines_of_business: ExtractedField = Field(..., description="Covered classes/lines of business as a list of strings.")
    currency: ExtractedField = Field(..., description="Contract currency (ISO code if identifiable, e.g. 'EUR').")

    treaty_rept_frequency_value: ExtractedField = Field(
        ..., description="Reporting frequency value (number, e.g. 3 for quarterly)."
    )
    treaty_settlement_exchange_rate_type: ExtractedField = Field(
        ..., description=(
            "Settlement/exchange rate type (e.g. 'current', 'fixed'). "
            "Current = Treaty payments are settled using current exchange rate. "
            "Fixed = Treaty payments are settled using a fixed exchange rate."
        )
    )

    # --- Structure / economics ---
    cession_percentage: ExtractedField = Field(
        ..., description="For quota share: ceded percentage (number, e.g. 30 for 30%)."
    )
    retention: ExtractedField = Field(
        ...,
        description=(
            "Cedent's retention: for quota share the retained percentage; for surplus the retained line; "
            "for XL the priority/deductible amount."
        ),
    )
    limit: ExtractedField = Field(
        ...,
        description=(
            "Reinsurer's limit of liability: per-risk/per-event cover amount for XL "
            "(the 'xs' cover, e.g. 40000000 for '40,000,000 xs 10,000,000'), number of lines for surplus, "
            "or maximum per-risk cession for quota share."
        ),
    )
    aggregate_limit: ExtractedField = Field(..., description="Annual aggregate limit of liability, if any.")
    reinstatements: ExtractedField = Field(
        ..., description="Number and cost of reinstatements, e.g. '2 @ 100% additional premium pro rata to amount'."
    )
    event_limit: ExtractedField = Field(..., description="Per-event limit / loss occurrence limit, if any.")


    # --- Premium ---
    premium_rate: ExtractedField = Field(
        ..., description="Premium rate on subject premium income (number, %), or flat premium amount context."
    )
    treaty_ratio: ExtractedField = Field(..., description="Treaty Reinsurance ratio, if any.", examples=[0.35, 0.45])
    treaty_share_ratio: ExtractedField = Field(..., description="Treaty share ratio, if any.", examples=[0.25, 0.70])

    minimum_premium: ExtractedField = Field(..., description="Minimum premium amount.")
    deposit_premium: ExtractedField = Field(..., description="Deposit/provisional premium amount and payment schedule.")
    adjustable_rate: ExtractedField = Field(
        ..., description="Adjustable/burning-cost rate details, e.g. 'min 1.5% max 4.5%, loading 100/70'."
    )
    premium_payment_terms: ExtractedField = Field(..., description="Premium payment schedule/instalments.")
    estimated_premium_income: ExtractedField = Field(
        ..., description="Estimated/Gross Net Premium Income (EPI/GNPI) the rates apply to."
    )

    #--- Commission Rate ---
    ceding_commission: ExtractedField = Field(
        ..., description="Flat ceding commission percentage, or provisional commission for sliding scale."
    )
    sliding_scale_commission: ExtractedField = Field(
        ..., description="Sliding scale terms: min/max commission and corresponding loss ratios."
    )
    profit_commission: ExtractedField = Field(
        ..., description="Profit commission percentage and basis (e.g. '20% after 5% management expenses')."
    )
    brokerage: ExtractedField = Field(..., description="Brokerage percentage, if stated.")
    loss_participation: ExtractedField = Field(
        ..., description="Loss participation / loss corridor clause details, if any."
    )

    # --- Legal / other ---
    exclusions: ExtractedField = Field(..., description="List of exclusions.")
    special_conditions: ExtractedField = Field(..., description="Notable special conditions/warranties as a list.")
    governing_law: ExtractedField = Field(..., description="Governing law / jurisdiction.")
    arbitration: ExtractedField = Field(..., description="Arbitration clause summary (seat, rules).")
    special_termination: ExtractedField = Field(..., description="Special termination / sudden death clause triggers.")


# ---------------------------------------------------------------------------
# Field catalog derived from the model — used by the API and by validation of
# manual edits/amendments, so the catalog can never drift from the schema.
# ---------------------------------------------------------------------------

def field_catalog() -> dict[str, str]:
    """Mapping of field_key -> description for every defined data point."""
    return {
        key: (info.description or key)
        for key, info in TreatyExtraction.model_fields.items()
    }


def field_label(key: str) -> str:
    """Human-readable label derived from the field key."""
    return key.replace("_", " ").title()


FIELD_KEYS: frozenset[str] = frozenset(TreatyExtraction.model_fields.keys())


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
    mapped against the defined data-point catalog."""

    summary: str = Field(..., description="One-paragraph summary of what the amendment changes.")
    effective_date: Optional[date] = Field(
        None, description="Date the amendment takes effect (ISO date), if stated."
    )
    changes: list[AmendedField] = Field(
        ..., description="Every data point whose value changes. Empty if the document changes nothing in the catalog."
    )
