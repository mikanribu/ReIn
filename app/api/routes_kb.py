"""Knowledge Base RAG endpoints: build the index and ask questions."""
import time

from fastapi import APIRouter, Depends, HTTPException
from langchain_core.language_models.chat_models import BaseChatModel
from sqlalchemy.orm import Session

from app import observability
from app.config import get_settings
from app.database import get_db
from app.schemas.api import (
    KbAnswer,
    KbAskRequest,
    KbIndexStatus,
    KbReindexResult,
    KbSource,
)
from app.services import rag as rag_service
from app.services.embeddings import Embedder, get_embeddings
from app.services.errors import translate_llm_errors
from app.services.llm import get_chat_model

router = APIRouter(prefix="/kb", tags=["knowledge-base"])


@router.get("/status", response_model=KbIndexStatus)
def status(
    db: Session = Depends(get_db),
    embedder: Embedder = Depends(get_embeddings),
) -> KbIndexStatus:
    """How much of the corpus is indexed for the current embedding model."""
    return KbIndexStatus(**rag_service.index_status(db, embedder))


@router.post("/reindex", response_model=KbReindexResult)
def reindex(
    db: Session = Depends(get_db),
    embedder: Embedder = Depends(get_embeddings),
) -> KbReindexResult:
    """(Re)build the semantic index over every treaty."""
    with translate_llm_errors("build the semantic index"), observability.run("kb.reindex"):
        t0 = time.perf_counter()
        stats = rag_service.reindex(db, embedder)
        observability.log_reindex(
            provider=get_settings().embeddings_provider,
            model_id=embedder.model_id,
            dim=stats["dim"],
            chunks=stats["indexed_chunks"],
            chars=stats["chars"],
            duration_s=time.perf_counter() - t0,
        )
    return KbReindexResult(indexed_chunks=stats["indexed_chunks"])


@router.get("/indexed")
def indexed(
    db: Session = Depends(get_db),
    embedder: Embedder = Depends(get_embeddings),
) -> dict:
    """Treaty ids currently in the semantic index for this embedding model."""
    return {
        "embedding_model": embedder.model_id,
        "treaty_ids": rag_service.indexed_treaty_ids(db, embedder.model_id),
    }


@router.post("/index/{treaty_id}")
def index_one(
    treaty_id: str,
    db: Session = Depends(get_db),
    embedder: Embedder = Depends(get_embeddings),
) -> dict:
    """(Re)index a single treaty (used to auto-index on ingest)."""
    with translate_llm_errors("index the treaty"):
        ok = rag_service.index_treaty(db, embedder, treaty_id)
    if not ok:
        raise HTTPException(404, f"Treaty {treaty_id} not found or has no version")
    return {"indexed": True}


@router.post("/ask", response_model=KbAnswer)
def ask(
    payload: KbAskRequest,
    db: Session = Depends(get_db),
    embedder: Embedder = Depends(get_embeddings),
    chat_llm: BaseChatModel = Depends(get_chat_model),
) -> KbAnswer:
    """Answer a question grounded in the most relevant indexed treaties."""
    with translate_llm_errors("answer the question"):
        answer, sources = rag_service.answer_question(chat_llm, embedder, db, payload.question)
    return KbAnswer(answer=answer, sources=[KbSource(**s) for s in sources])
