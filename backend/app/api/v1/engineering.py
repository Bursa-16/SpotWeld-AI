
from fastapi import APIRouter, Depends

from app.api.dependencies import require_permission
from app.application.engineering_service import EngineeringService
from app.models.entities import User
from app.schemas.engineering import (
    DynamicResistanceRequest,
    ElectrodeLifeRequest,
    PulseStrategyRequest,
    WeldLobeRequest,
)

router = APIRouter(prefix="/engineering", tags=["Engineering"])


def service() -> EngineeringService:
    return EngineeringService()


@router.post("/weld-lobe")
def weld_lobe(
    payload: WeldLobeRequest,
    svc: EngineeringService = Depends(service),
    _user: User = Depends(require_permission("weld:read")),
):
    return svc.weld_lobe(payload)


@router.post("/pulse-strategy")
def pulse_strategy(
    payload: PulseStrategyRequest,
    svc: EngineeringService = Depends(service),
    _user: User = Depends(require_permission("weld:read")),
):
    return svc.pulse_strategy(payload)


@router.post("/electrode-life")
def electrode_life(
    payload: ElectrodeLifeRequest,
    svc: EngineeringService = Depends(service),
    _user: User = Depends(require_permission("weld:read")),
):
    return svc.electrode_life(payload)


@router.post("/dynamic-resistance")
def dynamic_resistance(
    payload: DynamicResistanceRequest,
    svc: EngineeringService = Depends(service),
    _user: User = Depends(require_permission("weld:read")),
):
    return svc.dynamic_resistance(payload)
