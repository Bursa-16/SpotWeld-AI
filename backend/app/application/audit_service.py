
from sqlalchemy.orm import Session
from app.models.entities import AuditLog, User


def write_audit(
    db: Session,
    user: User | None,
    action: str,
    entity_type: str,
    entity_id: str = "",
    detail: dict | None = None,
) -> AuditLog:
    record = AuditLog(
        user_id=user.id if user else None,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        detail=detail or {},
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record
