
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import require_permission
from app.db.session import get_db
from app.models.entities import Approval, AuditLog, Project, User, WeldPoint
from app.schemas.dashboard import DashboardResponse

router = APIRouter(tags=["Dashboard"])


@router.get("/dashboard", response_model=DashboardResponse)
def dashboard(
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("project:read")),
):
    since = datetime.now(timezone.utc) - timedelta(days=7)

    return DashboardResponse(
        total_projects=db.scalar(select(func.count(Project.id))) or 0,
        active_projects=db.scalar(select(func.count(Project.id)).where(Project.status == "Aktif")) or 0,
        total_weld_points=db.scalar(select(func.count(WeldPoint.id))) or 0,
        risky_weld_points=db.scalar(
            select(func.count(WeldPoint.id)).where(
                WeldPoint.analysis_result["risk_level"].as_string().in_(["Orta", "Yüksek"])
            )
        ) or 0,
        pending_approvals=db.scalar(
            select(func.count(Approval.id)).where(Approval.status.in_(["Taslak", "İncelemede"]))
        ) or 0,
        rejected_approvals=db.scalar(
            select(func.count(Approval.id)).where(Approval.status == "Reddedildi")
        ) or 0,
        total_users=db.scalar(select(func.count(User.id))) or 0,
        recent_audit_events=db.scalar(
            select(func.count(AuditLog.id)).where(AuditLog.created_at >= since)
        ) or 0,
    )
