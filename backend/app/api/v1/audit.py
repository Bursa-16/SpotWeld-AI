
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import require_permission
from app.db.session import get_db
from app.models.entities import AuditLog, User

router = APIRouter(tags=["Audit"])


@router.get("/audit")
def list_audit(
    limit: int = 100,
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("*")),
):
    rows = db.scalars(
        select(AuditLog).order_by(AuditLog.created_at.desc()).limit(min(limit, 500))
    ).all()
    return [
        {
            "id": row.id,
            "user_id": row.user_id,
            "action": row.action,
            "entity_type": row.entity_type,
            "entity_id": row.entity_id,
            "detail": row.detail,
            "created_at": row.created_at,
        }
        for row in rows
    ]
