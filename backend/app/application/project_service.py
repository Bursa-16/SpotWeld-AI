from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.application.weld_analysis_service import WeldAnalysisService
from app.models import Approval, Project, WeldPoint, WeldPointRevision
from app.schemas.analysis import WeldAnalysisRequest
from app.schemas.projects import (
    ApprovalCreate, ProjectCreate, ProjectUpdate, WeldPointCreate, WeldPointUpdate,
)


class ProjectService:
    def __init__(self, db: Session):
        self.db = db
        self.analysis_service = WeldAnalysisService()

    def create_project(self, payload: ProjectCreate) -> Project:
        project = Project(**payload.model_dump())
        self.db.add(project)
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise HTTPException(status_code=409, detail="Project code already exists") from exc
        self.db.refresh(project)
        return project

    def list_projects(self) -> list[Project]:
        return list(self.db.scalars(select(Project).order_by(Project.updated_at.desc())))

    def get_project(self, project_id: int) -> Project:
        project = self.db.get(Project, project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        return project

    def update_project(self, project_id: int, payload: ProjectUpdate) -> Project:
        project = self.get_project(project_id)
        for key, value in payload.model_dump(exclude_unset=True).items():
            setattr(project, key, value)
        self.db.commit(); self.db.refresh(project)
        return project

    def delete_project(self, project_id: int) -> None:
        project = self.get_project(project_id)
        self.db.delete(project); self.db.commit()

    def create_weld_point(self, project_id: int, payload: WeldPointCreate) -> WeldPoint:
        self.get_project(project_id)
        request = WeldAnalysisRequest.model_validate(payload.analysis_input)
        analysis_result = self.analysis_service.analyze(request)
        data = payload.model_dump(exclude={"changed_by", "change_reason", "analysis_input"})
        point = WeldPoint(
            project_id=project_id,
            **data,
            analysis_input=payload.analysis_input,
            analysis_result=analysis_result,
        )
        self.db.add(point)
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise HTTPException(status_code=409, detail="Weld point code already exists in project") from exc
        self.db.refresh(point)
        return point

    def list_weld_points(self, project_id: int) -> list[WeldPoint]:
        self.get_project(project_id)
        stmt = select(WeldPoint).where(WeldPoint.project_id == project_id).order_by(WeldPoint.updated_at.desc())
        return list(self.db.scalars(stmt))

    def get_weld_point(self, point_id: int) -> WeldPoint:
        point = self.db.get(WeldPoint, point_id)
        if not point:
            raise HTTPException(status_code=404, detail="Weld point not found")
        return point

    def update_weld_point(self, point_id: int, payload: WeldPointUpdate) -> WeldPoint:
        point = self.get_weld_point(point_id)
        snapshot = {
            "point_code": point.point_code,
            "part_no": point.part_no,
            "part_revision": point.part_revision,
            "station": point.station,
            "robot": point.robot,
            "gun": point.gun,
            "operation_no": point.operation_no,
            "criticality": point.criticality,
            "approval_status": point.approval_status,
            "version_no": point.version_no,
            "analysis_input": point.analysis_input,
            "analysis_result": point.analysis_result,
        }
        revision = WeldPointRevision(
            weld_point_id=point.id,
            revision_no=point.version_no,
            changed_by=payload.changed_by,
            change_reason=payload.change_reason,
            snapshot=snapshot,
        )
        self.db.add(revision)

        update_data = payload.model_dump(exclude={"changed_by", "change_reason"}, exclude_unset=True)
        if "analysis_input" in update_data:
            request = WeldAnalysisRequest.model_validate(update_data["analysis_input"])
            point.analysis_input = update_data.pop("analysis_input")
            point.analysis_result = self.analysis_service.analyze(request)
        for key, value in update_data.items():
            setattr(point, key, value)
        point.version_no += 1
        self.db.commit(); self.db.refresh(point)
        return point

    def list_revisions(self, point_id: int) -> list[WeldPointRevision]:
        self.get_weld_point(point_id)
        stmt = select(WeldPointRevision).where(
            WeldPointRevision.weld_point_id == point_id
        ).order_by(WeldPointRevision.revision_no.desc())
        return list(self.db.scalars(stmt))

    def add_approval(self, point_id: int, payload: ApprovalCreate) -> Approval:
        point = self.get_weld_point(point_id)
        approval = Approval(weld_point_id=point_id, **payload.model_dump())
        point.approval_status = payload.status
        self.db.add(approval); self.db.commit(); self.db.refresh(approval)
        return approval

    def list_approvals(self, point_id: int) -> list[Approval]:
        self.get_weld_point(point_id)
        stmt = select(Approval).where(Approval.weld_point_id == point_id).order_by(Approval.created_at.desc())
        return list(self.db.scalars(stmt))
