"""LangChain extraction chains.

Two chains, both returning validated Pydantic objects via structured output:

* ``extract_treaty`` — parses a full treaty document into the defined
  data-point catalog (``TreatyExtraction``).
* ``extract_amendment`` — parses an adjustment/endorsement document and maps
  the changes onto the same catalog (``AmendmentExtraction``), given the
  treaty's current values as context.
"""
import json

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from app.config import get_settings
from app.schemas.treaty_fields import (
    FIELD_KEYS,
    AmendmentExtraction,
    TreatyExtraction,
)

EXTRACTION_SYSTEM_PROMPT = """\
You are a senior reinsurance treaty technician. You extract structured data
points from reinsurance treaty wordings (slips, contracts, cover notes).

Rules:
- Extract only what the document states. Never invent values.
- For every data point provide the exact supporting quote and its location
  (article/clause/page) so a human reviewer can verify it.
- Use value=null with confidence 0.0 for anything the document does not
  address; explain briefly in the rationale when a field is not applicable
  to this treaty type.
- Amounts: plain numbers without thousand separators. Percentages: the
  numeric value (25 for 25%). Dates: ISO format YYYY-MM-DD.
- If a value requires interpretation (e.g. deriving the retention from a
  layer description like '40,000,000 xs 10,000,000'), state the
  interpretation in the rationale and lower the confidence accordingly.
"""

AMENDMENT_SYSTEM_PROMPT = """\
You are a senior reinsurance treaty technician. You read a treaty
adjustment / endorsement / addendum document and determine exactly which of
the treaty's defined data points it changes.

Rules:
- Report only data points that actually change; leave everything else out.
- field_key must be one of the defined catalog keys you are given.
- For every change provide the new value, the exact supporting quote from
  the amendment document, and a short rationale.
- Use the same value conventions as the original extraction: plain numbers,
  percentages as numbers, ISO dates, lists of strings.
- If the amendment references a change that does not map to any catalog
  field, mention it in the summary but do not force it into a field.
"""


def _clip(text: str) -> str:
    limit = get_settings().max_document_chars
    if len(text) <= limit:
        return text
    return text[:limit] + "\n\n[DOCUMENT TRUNCATED]"


def extract_treaty(llm: BaseChatModel, document_text: str) -> TreatyExtraction:
    structured = llm.with_structured_output(TreatyExtraction)
    return structured.invoke(
        [
            SystemMessage(content=EXTRACTION_SYSTEM_PROMPT),
            HumanMessage(
                content=(
                    "Extract all defined data points from the following "
                    "reinsurance treaty document:\n\n<document>\n"
                    f"{_clip(document_text)}\n</document>"
                )
            ),
        ]
    )


def extract_amendment(
    llm: BaseChatModel,
    amendment_text: str,
    current_values: dict,
) -> AmendmentExtraction:
    structured = llm.with_structured_output(AmendmentExtraction)
    result: AmendmentExtraction = structured.invoke(
        [
            SystemMessage(content=AMENDMENT_SYSTEM_PROMPT),
            HumanMessage(
                content=(
                    "The treaty currently has these data points (field_key: value):\n"
                    f"{json.dumps(current_values, indent=2, default=str)}\n\n"
                    "Determine which data points are changed by the following "
                    "amendment document:\n\n<amendment>\n"
                    f"{_clip(amendment_text)}\n</amendment>"
                )
            ),
        ]
    )
    # Defensive: drop any hallucinated field keys so they can never reach the DB.
    result.changes = [c for c in result.changes if c.field_key in FIELD_KEYS]
    return result
