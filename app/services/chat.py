"""The treaty assistant chatbot.

A plain LLM chat — **no tools are bound to the model**, so it has no web
access or any other side effect; it can only reason over the conversation and
the treaty context we hand it. On a treaty page the caller passes ``treaty_id``
and we inject that treaty's data as context so answers are grounded; elsewhere
it acts as a general reinsurance / how-to-use-the-app assistant.
"""
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from sqlalchemy.orm import Session

from app.models import Treaty, TreatyVersion
from app.schemas.api import ChatMessage

GENERAL_SYSTEM = """\
You are TreatyIQ Assistant, a helpful expert on reinsurance treaties and on
using the TreatyIQ application (which parses treaties, extracts data points for
human review, versions them, and records amendments).

Rules:
- Answer from the conversation, any treaty context provided below, and your own
  general knowledge of reinsurance. You have NO internet access — never claim to
  look anything up online, fetch URLs, or cite live sources.
- Be concise and practical. Use plain text (short paragraphs or bullet points).
- If a question asks about a specific treaty's values and no treaty context is
  provided, say you can only answer treaty-specific questions from within that
  treaty's page.
- If the answer isn't in the provided context and you're not confident, say so
  rather than inventing figures. Never fabricate treaty numbers.
"""


def _treaty_context(db: Session, treaty_id: str) -> str | None:
    """Build a readable context block for one treaty, or None if not found."""
    treaty = db.get(Treaty, treaty_id)
    if treaty is None:
        return None

    versions = sorted(treaty.versions, key=lambda v: v.version_number)
    if not versions:
        return f"Treaty {treaty.reference} — {treaty.name}. No versions yet."

    latest = versions[-1]
    approved = next((v for v in reversed(versions)
                     if v.status == "approved"), None)

    lines = [
        "=== TREATY CONTEXT (use this to answer questions about this treaty) ===",
        f"Reference: {treaty.reference}",
        f"Name: {treaty.name}",
        f"Versions: " + ", ".join(
            f"v{v.version_number} ({v.status}, {v.origin.replace('_', ' ')}"
            + (f", effective {v.effective_date}" if v.effective_date else "") + ")"
            for v in versions
        ),
        f"In force: {'v' + str(approved.version_number) if approved else 'none approved yet'}",
        "",
        f"Data points (from the latest version, v{latest.version_number} [{latest.status}]):",
    ]
    for dp in sorted(latest.data_points, key=lambda d: d.field_label):
        if dp.value is None:
            continue
        loc = f" [{dp.source_location}]" if dp.source_location else ""
        lines.append(f"- {dp.field_label}: {dp.value}{loc}")
    lines.append("=== END TREATY CONTEXT ===")
    return "\n".join(lines)


def _to_lc_messages(system: str, history: list[ChatMessage]):
    msgs = [SystemMessage(content=system)]
    for m in history:
        if m.role == "assistant":
            msgs.append(AIMessage(content=m.content))
        else:
            msgs.append(HumanMessage(content=m.content))
    return msgs


def answer(
    llm: BaseChatModel,
    db: Session,
    history: list[ChatMessage],
    treaty_id: str | None,
) -> tuple[str, bool]:
    """Return (reply_text, grounded_in_treaty)."""
    system = GENERAL_SYSTEM
    grounded = False
    if treaty_id:
        ctx = _treaty_context(db, treaty_id)
        if ctx:
            system = f"{GENERAL_SYSTEM}\n\n{ctx}"
            grounded = True

    # No tools are bound → the model cannot browse the web or take actions.
    response = llm.invoke(_to_lc_messages(system, history))
    content = response.content if hasattr(response, "content") else str(response)
    if isinstance(content, list):  # some providers return content parts
        content = "".join(part.get("text", "") if isinstance(part, dict) else str(part)
                          for part in content)
    return content.strip(), grounded
