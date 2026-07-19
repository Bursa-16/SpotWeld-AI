from __future__ import annotations

from datetime import datetime
from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class ProjectCreate(BaseModel):
    project_code: str = Field(min_length=1, max_length=80)
    project_name: str = Field(min_length=1, max_length=200)
    customer: str = ""
    vehicle_platform: str = ""
    status: str = "Aktif"


class ProjectUpdate(BaseModel):
    project_name: str | None = None
    customer: str | None = None
    vehicle_platform: str | None = None
    status: str | None = None


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    project_code: str
    project_name: str
    customer: str
    vehicle_platform: str
    status: str
    created_at: datetime
    updated_at: datetime


class WeldPointCreate(BaseModel):
    point_code: str = Field(min_length=1, max_length=100)
    part_no: str = ""
    part_revision: str = ""
    station: str = ""
    robot: str = ""
    gun: str = ""
    operation_no: str = ""
    criticality: str = "Standart"
    changed_by: str = "Proses Mühendisi"
    change_reason: str = "İlk kayıt"
    analysis_input: dict[str, Any]


class WeldPointUpdate(BaseModel):
    part_no: str | None = None
    part_revision: str | None = None
    station: str | None = None
    robot: str | None = None
    gun: str | None = None
    operation_no: str | None = None
    criticality: str | None = None
    changed_by: str = Field(min_length=1)
    change_reason: str = Field(min_length=1)
    analysis_input: dict[str, Any] | None = None


class WeldPointResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    project_id: int
    point_code: str
    part_no: str
    part_revision: str
    station: str
    robot: str
    gun: str
    operation_no: str
    criticality: str
    approval_status: str
    version_no: int
    analysis_input: dict[str, Any]
    analysis_result: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class RevisionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    weld_point_id: int
    revision_no: int
    changed_by: str
    change_reason: str
    snapshot: dict[str, Any]
    created_at: datetime


class ApprovalCreate(BaseModel):
    approval_type: str
    approver: str = Field(min_length=1)
    status: str
    note: str = ""


class ApprovalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    weld_point_id: int
    approval_type: str
    approver: str
    status: str
    note: str
    created_at: datetime
