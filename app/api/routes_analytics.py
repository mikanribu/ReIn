"""Knowledge Base analytics endpoints (deterministic aggregations)."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.api import PortfolioAnalytics
from app.services import analytics as analytics_service

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/portfolio", response_model=PortfolioAnalytics)
def portfolio(db: Session = Depends(get_db)) -> PortfolioAnalytics:
    """Counts per categorical dimension and numeric totals per currency,
    computed over the latest version of every treaty."""
    return PortfolioAnalytics(**analytics_service.portfolio_analytics(db))
