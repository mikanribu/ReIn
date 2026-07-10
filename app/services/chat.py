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

# Appended only when a treaty context is present, so the assistant declares
# which fields it used. We validate the labels against the treaty's real fields
# afterwards, so a hallucinated label is dropped rather than shown.
CITATION_INSTRUCTION = """\
When your answer uses specific values from the TREATY CONTEXT above, finish your
reply with a single final line listing the exact field labels you used, formatted
exactly as:
SOURCES: Field Label; Another Field Label
Use the field labels exactly as they appear in the context. Do not invent labels.
If your answer doesn't rely on any specific field, omit the SOURCES line entirely.
"""


def _treaty_context(db: Session, treaty_id: str) -> tuple[str, list[str]] | None:
    """Build a readable context block for one treaty and the list of field
    labels it exposes, or None if the treaty isn't found."""
    treaty = db.get(Treaty, treaty_id)
    if treaty is None:
        return None

    versions = sorted(treaty.versions, key=lambda v: v.version_number)
    if not versions:
        return f"Treaty {treaty.reference} — {treaty.name}. No versions yet.", []

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
    labels: list[str] = []
    for dp in sorted(latest.data_points, key=lambda d: d.field_label):
        if dp.value is None:
            continue
        labels.append(dp.field_label)
        loc = f" [{dp.source_location}]" if dp.source_location else ""
        lines.append(f"- {dp.field_label}: {dp.value}{loc}")
    lines.append("=== END TREATY CONTEXT ===")
    return "\n".join(lines), labels


def _extract_sources(reply: str, valid_labels: list[str]) -> tuple[str, list[str]]:
    """Pull a trailing ``SOURCES: a; b`` line off the reply, keeping only labels
    that match a real field (case-insensitive). Returns (clean_reply, citations)."""
    if not valid_labels:
        return reply, []
    lines = reply.splitlines()
    # Only the last non-empty line counts; sources must sit at the very end.
    for i in range(len(lines) - 1, -1, -1):
        line = lines[i].strip()
        if not line:
            continue
        if line.upper().startswith("SOURCES:"):
            raw = line.split(":", 1)[1]
            by_lower = {label.lower(): label for label in valid_labels}
            citations: list[str] = []
            for part in raw.split(";"):
                canonical = by_lower.get(part.strip().lower())
                if canonical and canonical not in citations:
                    citations.append(canonical)
            clean = "\n".join(lines[:i]).rstrip()
            return clean, citations
        break  # a non-empty, non-SOURCES last line → nothing to extract
    return reply, []


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
) -> tuple[str, bool, list[str]]:
    """Return (reply_text, grounded_in_treaty, cited_field_labels)."""
    system = GENERAL_SYSTEM
    grounded = False
    labels: list[str] = []
    if treaty_id:
        ctx = _treaty_context(db, treaty_id)
        if ctx:
            context_str, labels = ctx
            system = f"{GENERAL_SYSTEM}\n\n{context_str}\n\n{CITATION_INSTRUCTION}"
            grounded = True

    # No tools are bound → the model cannot browse the web or take actions.
    response = llm.invoke(_to_lc_messages(system, history))
    content = response.content if hasattr(response, "content") else str(response)
    if isinstance(content, list):  # some providers return content parts
        content = "".join(part.get("text", "") if isinstance(part, dict) else str(part)
                          for part in content)
    reply, citations = _extract_sources(content.strip(), labels)
    return reply, grounded, citations
