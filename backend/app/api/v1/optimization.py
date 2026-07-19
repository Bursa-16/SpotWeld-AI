from fastapi import APIRouter, Depends
from app.api.dependencies import require_permission
from app.application.optimization_service import OptimizationService
from app.models.entities import User
from app.schemas.optimization import DoeOptimizationRequest,EnsembleRequest,Model4Input,ModelValidationRequest
router=APIRouter(prefix='/optimization',tags=['Optimization'])
def service(): return OptimizationService()
@router.post('/model4/predict')
def model4_predict(payload:Model4Input,svc:OptimizationService=Depends(service),_user:User=Depends(require_permission('weld:read'))): return svc.model4_predict(payload)
@router.post('/ensemble')
def ensemble_predict(payload:EnsembleRequest,svc:OptimizationService=Depends(service),_user:User=Depends(require_permission('weld:read'))): return svc.ensemble(payload)
@router.post('/doe')
def doe_optimize(payload:DoeOptimizationRequest,svc:OptimizationService=Depends(service),_user:User=Depends(require_permission('weld:read'))): return svc.optimize(payload)
@router.post('/model4/validate')
def validate_model4(payload:ModelValidationRequest,svc:OptimizationService=Depends(service),_user:User=Depends(require_permission('weld:read'))): return svc.validate_model4(payload)
