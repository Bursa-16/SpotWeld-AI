from fastapi import APIRouter
router=APIRouter(tags=["System"])
@router.get("/health")
def health(): return {"status":"ok","service":"spot-welding-platform"}
