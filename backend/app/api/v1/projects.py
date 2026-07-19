from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.application.project_service import ProjectService
from app.api.dependencies import require_permission
from app.models.entities import User
from app.db.session import get_db
from app.schemas.projects import (
    ApprovalCreate, ApprovalResponse, ProjectCreate, ProjectResponse, ProjectUpdate,
    RevisionResponse, WeldPointCreate, WeldPointResponse, WeldPointUpdate,
)

router = APIRouter(tags=["Projects"])


def service(db: Session = Depends(get_db)) -> ProjectService:
    return ProjectService(db)


@router.post("/projects", response_model=ProjectResponse, status_code=201)
def create_project(payload: ProjectCreate, svc: ProjectService = Depends(service), _user: User = Depends(require_permission("project:write"))):
    return svc.create_project(payload)


@router.get("/projects", response_model=list[ProjectResponse])
def list_projects(svc: ProjectService = Depends(service), _user: User = Depends(require_permission("project:read"))):
    return svc.list_projects()


@router.get("/projects/{project_id}", response_model=ProjectResponse)
def get_project(project_id: int, svc: ProjectService = Depends(service), _user: User = Depends(require_permission("project:read"))):
    return svc.get_project(project_id)


@router.patch("/projects/{project_id}", response_model=ProjectResponse)
def update_project(project_id: int, payload: ProjectUpdate, svc: ProjectService = Depends(service), _user: User = Depends(require_permission("project:write"))):
    return svc.update_project(project_id, payload)


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(project_id: int, svc: ProjectService = Depends(service), _user: User = Depends(require_permission("project:write"))):
    svc.delete_project(project_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/projects/{project_id}/weld-points", response_model=WeldPointResponse, status_code=201)
def create_weld_point(project_id: int, payload: WeldPointCreate, svc: ProjectService = Depends(service), _user: User = Depends(require_permission("weld:write"))):
    return svc.create_weld_point(project_id, payload)


@router.get("/projects/{project_id}/weld-points", response_model=list[WeldPointResponse])
def list_weld_points(project_id: int, svc: ProjectService = Depends(service), _user: User = Depends(require_permission("weld:read"))):
    return svc.list_weld_points(project_id)


@router.get("/weld-points/{point_id}", response_model=WeldPointResponse)
def get_weld_point(point_id: int, svc: ProjectService = Depends(service), _user: User = Depends(require_permission("weld:read"))):
    return svc.get_weld_point(point_id)


@router.patch("/weld-points/{point_id}", response_model=WeldPointResponse)
def update_weld_point(point_id: int, payload: WeldPointUpdate, svc: ProjectService = Depends(service), _user: User = Depends(require_permission("weld:write"))):
    return svc.update_weld_point(point_id, payload)


@router.get("/weld-points/{point_id}/revisions", response_model=list[RevisionResponse])
def list_revisions(point_id: int, svc: ProjectService = Depends(service), _user: User = Depends(require_permission("weld:read"))):
    return svc.list_revisions(point_id)


@router.post("/weld-points/{point_id}/approvals", response_model=ApprovalResponse, status_code=201)
def add_approval(point_id: int, payload: ApprovalCreate, svc: ProjectService = Depends(service), _user: User = Depends(require_permission("approval:write"))):
    return svc.add_approval(point_id, payload)


@router.get("/weld-points/{point_id}/approvals", response_model=list[ApprovalResponse])
def list_approvals(point_id: int, svc: ProjectService = Depends(service), _user: User = Depends(require_permission("approval:read"))):
    return svc.list_approvals(point_id)
