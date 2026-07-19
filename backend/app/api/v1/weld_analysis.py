from fastapi import APIRouter, Depends
from app.schemas.analysis import WeldAnalysisRequest, WeldAnalysisResponse
from app.application.weld_analysis_service import WeldAnalysisService
router=APIRouter(prefix="/weld-analysis",tags=["Weld Analysis"])
def get_service(): return WeldAnalysisService()
@router.post("",response_model=WeldAnalysisResponse)
def analyze_weld(payload:WeldAnalysisRequest,service:WeldAnalysisService=Depends(get_service)):
    return service.analyze(payload)
