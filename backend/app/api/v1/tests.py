
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import require_permission
from app.application.audit_service import write_audit
from app.db.session import get_db
from app.models.entities import TestResult, User, WeldPoint
from app.schemas.tests import TestResultCreate, TestResultResponse

router = APIRouter(tags=["Tests"])


@router.post("/weld-points/{point_id}/tests", response_model=TestResultResponse, status_code=201)
def create_test_result(
    point_id: int,
    payload: TestResultCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("test:write")),
):
    if not db.get(WeldPoint, point_id):
        raise HTTPException(status_code=404, detail="Weld point not found")

    row = TestResult(
        weld_point_id=point_id,
        created_by=user.email,
        **payload.model_dump(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    write_audit(db, user, "CREATE", "TestResult", str(row.id), {"weld_point_id": point_id})
    return row


@router.get("/weld-points/{point_id}/tests", response_model=list[TestResultResponse])
def list_test_results(
    point_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("test:read")),
):
    return list(
        db.scalars(
            select(TestResult)
            .where(TestResult.weld_point_id == point_id)
            .order_by(TestResult.created_at.desc())
        ).all()
    )
