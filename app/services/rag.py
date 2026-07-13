"""Retrieval-augmented Q&A over the treaty corpus.

Pipeline: render each treaty into a compact text chunk → embed → store. At
question time, embed the question, retrieve the most similar chunks by cosine
similarity, and ask the chat model to answer **using only those chunks**, with
citations to the source treaties. No tools are bound to the model, so it has no
web access — retrieval is the only external input, and it's all local data.
"""
import math

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Treaty, TreatyChunk, TreatyVersion
from app.services import analytics as analytics_service
from app.services.embeddings import Embedder

SYSTEM_PROMPT = """\
You are a reinsurance knowledge assistant answering questions about a portfolio
of treaties. You are given excerpts from the most relevant treaties as CONTEXT.

Rules:
- Answer using ONLY the CONTEXT. If the answer isn't in it, say you couldn't find
  it in the indexed treaties — do not guess or use outside knowledge.
- You have NO internet access — never claim to look anything up online.
- Cite the treaties you used by their reference (e.g. CAT-XL-2026-001).
- Be concise. When listing treaties that match, name each one.
"""


def _chunk_text(treaty: Treaty, version: TreatyVersion) -> str:
    """A compact, retrievable rendering of one treaty's key data points."""
    lines = [f"Treaty {treaty.reference}: {treaty.name}"]
    for dp in sorted(version.data_points, key=lambda d: d.field_key):
        if dp.value in (None, "", []):
            continue
        value = ", ".join(map(str, dp.value)) if isinstance(dp.value, list) else dp.value
        lines.append(f"{dp.field_label}: {value}")
        if dp.source_quote:
            lines.append(f'  ("{dp.source_quote}")')
    return "\n".join(lines)


def reindex(db: Session, embedder: Embedder) -> dict:
    """Rebuild the whole semantic index. Returns build stats
    (indexed_chunks, chars, dim) for logging."""
    db.execute(delete(TreatyChunk))
    pairs = list(analytics_service._latest_versions(db))
    if not pairs:
        db.commit()
        return {"indexed_chunks": 0, "chars": 0, "dim": 0}

    contents = [_chunk_text(t, v) for t, v in pairs]
    vectors = embedder.embed_documents(contents)
    for (treaty, _version), content, vector in zip(pairs, contents, vectors):
        db.add(TreatyChunk(
            treaty_id=treaty.id,
            treaty_reference=treaty.reference,
            treaty_name=treaty.name,
            content=content,
            embedding=list(vector),
            embedding_model=embedder.model_id,
        ))
    db.commit()
    return {
        "indexed_chunks": len(contents),
        "chars": sum(len(c) for c in contents),
        "dim": len(vectors[0]) if vectors else 0,
    }


def index_treaty(db: Session, embedder: Embedder, treaty_id: str) -> bool:
    """(Re)index a single treaty so it's immediately searchable in Ask.
    Replaces any existing chunks for that treaty. Returns False if not found."""
    treaty = db.get(Treaty, treaty_id)
    if treaty is None or not treaty.versions:
        return False
    version = max(treaty.versions, key=lambda v: v.version_number)
    db.execute(delete(TreatyChunk).where(TreatyChunk.treaty_id == treaty_id))
    content = _chunk_text(treaty, version)
    vector = embedder.embed_documents([content])[0]
    db.add(TreatyChunk(
        treaty_id=treaty.id,
        treaty_reference=treaty.reference,
        treaty_name=treaty.name,
        content=content,
        embedding=list(vector),
        embedding_model=embedder.model_id,
    ))
    db.commit()
    return True


def indexed_treaty_ids(db: Session, model_id: str) -> list[str]:
    """Treaty ids that have a chunk for the given embedding model."""
    rows = db.execute(
        select(TreatyChunk.treaty_id).where(TreatyChunk.embedding_model == model_id)
    ).scalars().all()
    return sorted(set(rows))


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def retrieve(db: Session, embedder: Embedder, question: str, k: int) -> list[dict]:
    """Top-k most similar chunks (for the current embedding model)."""
    chunks = db.execute(
        select(TreatyChunk).where(TreatyChunk.embedding_model == embedder.model_id)
    ).scalars().all()
    if not chunks:
        return []
    q = embedder.embed_query(question)
    scored = [
        {
            "treaty_id": c.treaty_id,
            "reference": c.treaty_reference,
            "name": c.treaty_name,
            "content": c.content,
            "score": _cosine(q, c.embedding),
        }
        for c in chunks
    ]
    scored.sort(key=lambda s: s["score"], reverse=True)
    return scored[:k]


def index_status(db: Session, embedder: Embedder) -> dict:
    total_treaties = db.execute(select(Treaty)).scalars().all()
    indexed = db.execute(
        select(TreatyChunk).where(TreatyChunk.embedding_model == embedder.model_id)
    ).scalars().all()
    return {
        "embedding_model": embedder.model_id,
        "indexed_chunks": len(indexed),
        "total_treaties": len(total_treaties),
        "ready": len(indexed) > 0,
    }


def answer_question(
    chat_llm: BaseChatModel,
    embedder: Embedder,
    db: Session,
    question: str,
) -> tuple[str, list[dict]]:
    """Return (answer_text, sources) for a corpus question."""
    k = get_settings().rag_top_k
    hits = retrieve(db, embedder, question, k)
    if not hits:
        return (
            "The knowledge base has no indexed treaties yet. Ingest treaties and "
            "build the index first.",
            [],
        )

    context = "\n\n".join(
        f"[{h['reference']}] {h['content']}" for h in hits
    )
    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=f"CONTEXT:\n{context}\n\nQUESTION: {question}"),
    ]
    response = chat_llm.invoke(messages)
    content = response.content if hasattr(response, "content") else str(response)
    if isinstance(content, list):
        content = "".join(part.get("text", "") if isinstance(part, dict) else str(part)
                          for part in content)

    # Cite the treaties actually named in the answer; fall back to top hits.
    cited = [h for h in hits if h["reference"] in content]
    sources = [{"treaty_id": h["treaty_id"], "reference": h["reference"], "name": h["name"]}
               for h in (cited or hits)]
    # De-duplicate while preserving order.
    seen, unique = set(), []
    for s in sources:
        if s["reference"] not in seen:
            seen.add(s["reference"])
            unique.append(s)
    return content.strip(), unique
