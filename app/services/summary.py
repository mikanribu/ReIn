"""Portfolio summarization.

The LLM writes the narrative, but it is fed the *deterministic* analytics
(the same numbers the Insights charts use) plus a capped list of treaty
one-liners — and instructed to use only those figures. So the prose is
readable but the facts and counts come from the database, not the model.
"""
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy.orm import Session

from app.services import analytics as analytics_service

# Cap how many treaties are listed individually (the aggregate figures always
# cover the whole book regardless).
_MAX_TREATIES_LISTED = 60

SYSTEM_PROMPT = """\
You are a reinsurance portfolio analyst. Write a concise executive summary of the
treaty portfolio described in the DATA below.

Rules:
- Use ONLY the figures and facts in the DATA. Never invent numbers, treaty names,
  cedents or currencies. If something isn't in the DATA, don't mention it.
- You have NO internet access — never claim to look anything up online.
- Cover: the size of the book, the mix by treaty type, the currency spread, and
  total exposure/premium by currency. Call out any notable concentration.
- Be professional and concise: 2–4 short paragraphs or a few bullets. No preamble
  like "Here is the summary"; just write it.
"""


def _brief(db: Session) -> tuple[str, int]:
    """A compact, factual portfolio brief for the model. Returns (text, count)."""
    a = analytics_service.portfolio_analytics(db)
    total = a["total_treaties"]
    lines = [f"Total treaties: {total}", ""]

    for b in a["breakdowns"]:
        counts = ", ".join(f"{bucket['value']}: {bucket['count']}" for bucket in b["buckets"])
        lines.append(f"By {b['label']}: {counts}")
    lines.append("")

    lines.append("Totals by currency (amounts summed within each currency):")
    for r in a["by_currency"]:
        lines.append(
            f"- {r['currency']}: {r['count']} treaties; "
            f"layer limit {r['layer_limit_amount']:,.0f}; "
            f"max cedant retention {r['maximum_cedant_retention_amount']:,.0f}"
        )

    # A capped list of individual treaties for texture.
    listed = list(analytics_service._latest_versions(db))
    lines.append("")
    lines.append(f"Treaties (up to {_MAX_TREATIES_LISTED} listed):")
    for treaty, version in listed[:_MAX_TREATIES_LISTED]:
        values = {dp.field_key: dp.value for dp in version.data_points}
        facts = [treaty.reference]
        if values.get("treaty_type"):
            facts.append(str(values["treaty_type"]).replace("_", " "))
        if values.get("contract_currency_code"):
            facts.append(str(values["contract_currency_code"]))
        if values.get("cedant_name"):
            facts.append(f"cedant {values['cedant_name']}")
        lines.append("- " + " — ".join(facts))
    if len(listed) > _MAX_TREATIES_LISTED:
        lines.append(f"…and {len(listed) - _MAX_TREATIES_LISTED} more.")

    return "\n".join(lines), total


def summarize_portfolio(llm: BaseChatModel, db: Session) -> str:
    """Return an executive-summary narrative grounded in the analytics."""
    brief, total = _brief(db)
    if total == 0:
        return "There are no treaties in the knowledge base yet. Ingest some treaties to generate a summary."

    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=f"DATA:\n{brief}\n\nWrite the executive summary."),
    ]
    response = llm.invoke(messages)
    content = response.content if hasattr(response, "content") else str(response)
    if isinstance(content, list):
        content = "".join(part.get("text", "") if isinstance(part, dict) else str(part)
                          for part in content)
    return content.strip()
