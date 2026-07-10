"""Portfolio-level KPIs, shared by the /stats endpoint and the chat assistant."""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    AuditLog,
    Document,
    Treaty,
    TreatyVersion,
    VersionOrigin,
    VersionStatus,
)
from app.schemas.api import StatsOut


def compute_stats(db: Session) -> StatsOut:
    """High-level KPIs for the home dashboard."""
    def count(stmt) -> int:
        return db.execute(stmt).scalar_one() or 0

    treaties = count(select(func.count()).select_from(Treaty))
    awaiting_review = count(
        select(func.count()).select_from(TreatyVersion)
        .where(TreatyVersion.status == VersionStatus.DRAFT)
    )
    approved_versions = count(
        select(func.count()).select_from(TreatyVersion)
        .where(TreatyVersion.status == VersionStatus.APPROVED)
    )
    in_force = count(
        select(func.count(func.distinct(TreatyVersion.treaty_id)))
        .where(TreatyVersion.status == VersionStatus.APPROVED)
    )
    amendments = count(
        select(func.count()).select_from(TreatyVersion)
        .where(TreatyVersion.origin.in_(
            [VersionOrigin.AMENDMENT_DOCUMENT, VersionOrigin.MANUAL_AMENDMENT]))
    )
    documents = count(select(func.count()).select_from(Document))
    audit_entries = count(select(func.count()).select_from(AuditLog))

    return StatsOut(
        treaties=treaties,
        in_force=in_force,
        awaiting_review=awaiting_review,
        amendments=amendments,
        approved_versions=approved_versions,
        documents=documents,
        audit_entries=audit_entries,
    )
