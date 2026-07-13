"""Knowledge Base analytics endpoints (deterministic aggregations)."""
from fastapi import APIRouter, Depends
from langchain_core.language_models.chat_models import BaseChatModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.api import PortfolioAnalytics, PortfolioSummary
from app.services import analytics as analytics_service
from app.services import summary as summary_service
from app.services.errors import translate_llm_errors
from app.services.llm import get_chat_model

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/portfolio", response_model=PortfolioAnalytics)
def portfolio(db: Session = Depends(get_db)) -> PortfolioAnalytics:
    """Counts per categorical dimension and numeric totals per currency,
    computed over the latest version of every treaty."""
    return PortfolioAnalytics(**analytics_service.portfolio_analytics(db))


@router.post("/summary", response_model=PortfolioSummary)
def portfolio_summary(
    db: Session = Depends(get_db),
    llm: BaseChatModel = Depends(get_chat_model),
) -> PortfolioSummary:
    """An LLM executive summary of the portfolio, grounded in the exact
    analytics figures (the model is told to use only those numbers)."""
    with translate_llm_errors("summarize the portfolio"):
        text = summary_service.summarize_portfolio(llm, db)
    return PortfolioSummary(summary=text)
