"""Chat assistant endpoint."""
from fastapi import APIRouter, Depends, HTTPException
from langchain_core.language_models.chat_models import BaseChatModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.api import ChatRequest, ChatResponse
from app.services import chat as chat_service
from app.services.errors import translate_llm_errors
from app.services.llm import get_chat_model

router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
def chat(
    payload: ChatRequest,
    db: Session = Depends(get_db),
    llm: BaseChatModel = Depends(get_chat_model),
) -> ChatResponse:
    """Answer a question. If treaty_id is given, the reply is grounded in that
    treaty's data. The model has no tools, so it cannot access the web."""
    if not payload.messages:
        raise HTTPException(422, "messages must not be empty")
    with translate_llm_errors("answer the question"):
        reply, grounded, citations = chat_service.answer(
            llm, db, payload.messages, payload.treaty_id
        )
    return ChatResponse(
        reply=reply, grounded_in_treaty=grounded, citations=citations
    )
