
from fastapi import APIRouter, Depends

from app.api.dependencies import require_permission
from app.application.failure_probability_service import FailureProbabilityService
from app.models.entities import User
from app.schemas.failure_probability import FailureProbabilityRequest

router = APIRouter(prefix="/failure-probability", tags=["Failure Probability"])


def service() -> FailureProbabilityService:
    return FailureProbabilityService()


@router.post("/analyze")
def analyze(
    payload: FailureProbabilityRequest,
    svc: FailureProbabilityService = Depends(service),
    _user: User = Depends(require_permission("weld:read")),
):
    return svc.analyze(payload)
