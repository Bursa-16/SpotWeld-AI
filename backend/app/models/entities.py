from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_code: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    project_name: Mapped[str] = mapped_column(String(200))
    customer: Mapped[str] = mapped_column(String(200), default="")
    vehicle_platform: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[str] = mapped_column(String(40), default="Aktif")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    weld_points: Mapped[list["WeldPoint"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class WeldPoint(Base):
    __tablename__ = "weld_points"
    __table_args__ = (UniqueConstraint("project_id", "point_code", name="uq_project_point"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    point_code: Mapped[str] = mapped_column(String(100), index=True)
    part_no: Mapped[str] = mapped_column(String(120), default="")
    part_revision: Mapped[str] = mapped_column(String(40), default="")
    station: Mapped[str] = mapped_column(String(100), default="")
    robot: Mapped[str] = mapped_column(String(100), default="")
    gun: Mapped[str] = mapped_column(String(100), default="")
    operation_no: Mapped[str] = mapped_column(String(100), default="")
    criticality: Mapped[str] = mapped_column(String(50), default="Standart")
    approval_status: Mapped[str] = mapped_column(String(50), default="Taslak")

    analysis_input: Mapped[dict] = mapped_column(JSON)
    analysis_result: Mapped[dict] = mapped_column(JSON)
    version_no: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    project: Mapped[Project] = relationship(back_populates="weld_points")
    revisions: Mapped[list["WeldPointRevision"]] = relationship(
        back_populates="weld_point", cascade="all, delete-orphan"
    )
    approvals: Mapped[list["Approval"]] = relationship(
        back_populates="weld_point", cascade="all, delete-orphan"
    )


class WeldPointRevision(Base):
    __tablename__ = "weld_point_revisions"
    __table_args__ = (UniqueConstraint("weld_point_id", "revision_no", name="uq_point_revision"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    weld_point_id: Mapped[int] = mapped_column(ForeignKey("weld_points.id", ondelete="CASCADE"), index=True)
    revision_no: Mapped[int] = mapped_column(Integer)
    changed_by: Mapped[str] = mapped_column(String(150))
    change_reason: Mapped[str] = mapped_column(Text)
    snapshot: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    weld_point: Mapped[WeldPoint] = relationship(back_populates="revisions")


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    weld_point_id: Mapped[int] = mapped_column(ForeignKey("weld_points.id", ondelete="CASCADE"), index=True)
    approval_type: Mapped[str] = mapped_column(String(80))
    approver: Mapped[str] = mapped_column(String(150))
    status: Mapped[str] = mapped_column(String(50))
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    weld_point: Mapped[WeldPoint] = relationship(back_populates="approvals")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(80), default="Read Only", index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(100), index=True)
    entity_type: Mapped[str] = mapped_column(String(100), index=True)
    entity_id: Mapped[str] = mapped_column(String(100), default="")
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class TestResult(Base):
    __tablename__ = "test_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    weld_point_id: Mapped[int] = mapped_column(ForeignKey("weld_points.id", ondelete="CASCADE"), index=True)
    test_type: Mapped[str] = mapped_column(String(100))
    result_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    result_unit: Mapped[str] = mapped_column(String(40), default="")
    acceptance_status: Mapped[str] = mapped_column(String(50))
    note: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
