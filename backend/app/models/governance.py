from __future__ import annotations

from datetime import datetime
from enum import Enum as PythonEnum
from typing import TypeVar

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    event,
    inspect,
)
from sqlalchemy.orm import Mapped, Mapper, mapped_column
from sqlalchemy.types import TypeDecorator

from app.db.session import Base
from app.domain.governance_types import ImmutableRecordError
from app.domain.idempotency_types import CommandReceiptStatus
from app.models.entities import utc_now


EnumType = TypeVar("EnumType", bound=PythonEnum)


class FrozenDict(dict):
    """JSON-compatible mapping that cannot be changed after construction."""

    def _immutable(self, *_args, **_kwargs):
        raise TypeError("governed JSON snapshots are immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable
    __ior__ = _immutable


def freeze_json(value):
    if isinstance(value, dict):
        return FrozenDict({key: freeze_json(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(freeze_json(item) for item in value)
    if isinstance(value, tuple):
        return tuple(freeze_json(item) for item in value)
    return value


class ImmutableJSON(TypeDecorator):
    impl = JSON
    cache_ok = True

    def process_bind_param(self, value, _dialect):
        return freeze_json(value)

    def process_result_value(self, value, _dialect):
        return freeze_json(value)


def freeze_json_attribute(attribute) -> None:
    event.listen(
        attribute,
        "set",
        lambda _target, value, _old_value, _initiator: freeze_json(value),
        retval=True,
    )


def portable_enum(enum_class: type[EnumType], constraint_name: str) -> Enum:
    return Enum(
        enum_class,
        name=constraint_name,
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        values_callable=lambda members: [member.value for member in members],
    )


def _reject_scalar_update(mapper: Mapper, _connection, target: object) -> None:
    state = inspect(target)
    changed_columns = [
        attribute.key
        for attribute in mapper.column_attrs
        if state.attrs[attribute.key].history.has_changes()
    ]
    if changed_columns:
        fields = ", ".join(sorted(changed_columns))
        raise ImmutableRecordError(
            f"{type(target).__name__} is append-only; changed fields: {fields}"
        )


def _reject_delete(_mapper: Mapper, _connection, target: object) -> None:
    raise ImmutableRecordError(f"{type(target).__name__} is append-only and cannot be deleted")


def protect_immutable_model(model: type[Base]) -> None:
    event.listen(model, "before_update", _reject_scalar_update)
    event.listen(model, "before_delete", _reject_delete)


class GovernedAuditEvent(Base):
    __tablename__ = "governed_audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(120), unique=True)
    entity_type: Mapped[str] = mapped_column(String(100), index=True)
    entity_id: Mapped[str] = mapped_column(String(120), index=True)
    entity_revision: Mapped[str] = mapped_column(String(80))
    action: Mapped[str] = mapped_column(String(100))
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    actor_id: Mapped[str] = mapped_column(String(200))
    actor_type: Mapped[str] = mapped_column(String(40))
    actor_role: Mapped[str | None] = mapped_column(String(100), nullable=True)
    authority_scope: Mapped[dict | None] = mapped_column(ImmutableJSON, nullable=True)
    reason: Mapped[str] = mapped_column(Text)
    correlation_id: Mapped[str] = mapped_column(String(120), index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    schema_version: Mapped[str] = mapped_column(String(40))
    software_version: Mapped[str] = mapped_column(String(80))
    canonicalization_version: Mapped[str] = mapped_column(String(40))
    hash_algorithm: Mapped[str] = mapped_column(String(40))
    prior_content_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    new_content_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    detail: Mapped[dict | None] = mapped_column(ImmutableJSON, nullable=True)
    correction_of_event_id: Mapped[int | None] = mapped_column(
        ForeignKey("governed_audit_events.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class GovernedCommandReceipt(Base):
    """Durable idempotency receipt for a governed command identity."""

    __tablename__ = "governed_command_receipts"
    __table_args__ = (
        UniqueConstraint(
            "command_namespace",
            "command_scope",
            "idempotency_key",
            name="uq_governed_command_receipts_command_identity",
        ),
        CheckConstraint(
            "(status = 'RESERVED' AND completed_at IS NULL "
            "AND result_type IS NULL AND result_id IS NULL "
            "AND result_revision IS NULL) OR "
            "(status = 'COMPLETED' AND completed_at IS NOT NULL "
            "AND result_type IS NOT NULL AND result_id IS NOT NULL "
            "AND result_revision IS NOT NULL)",
            name="ck_governed_command_receipts_completion_shape",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    receipt_id: Mapped[str] = mapped_column(String(120), unique=True)
    command_namespace: Mapped[str] = mapped_column(String(120))
    command_scope: Mapped[str] = mapped_column(String(200))
    idempotency_key: Mapped[str] = mapped_column(String(120))
    request_hash: Mapped[str] = mapped_column(String(128))
    status: Mapped[CommandReceiptStatus] = mapped_column(
        portable_enum(
            CommandReceiptStatus,
            "ck_governed_command_receipts_status",
        )
    )
    result_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    result_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    result_revision: Mapped[str | None] = mapped_column(String(80), nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(120), index=True)
    schema_version: Mapped[str] = mapped_column(String(40))
    software_version: Mapped[str] = mapped_column(String(80))
    canonicalization_version: Mapped[str] = mapped_column(String(40))
    hash_algorithm: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


def _guard_command_receipt_update(mapper: Mapper, _connection, target: object) -> None:
    state = inspect(target)
    changed_columns = {
        attribute.key
        for attribute in mapper.column_attrs
        if state.attrs[attribute.key].history.has_changes()
    }
    status_history = state.attrs.status.history
    prior_status = status_history.deleted[0] if status_history.deleted else target.status
    completion_fields = {
        "status",
        "result_type",
        "result_id",
        "result_revision",
        "completed_at",
    }
    if not (
        prior_status == CommandReceiptStatus.RESERVED
        and target.status == CommandReceiptStatus.COMPLETED
        and changed_columns == completion_fields
    ):
        fields = ", ".join(sorted(changed_columns)) or "none"
        raise ImmutableRecordError(
            "GovernedCommandReceipt permits only one RESERVED-to-COMPLETED "
            f"transition; changed fields: {fields}"
        )


freeze_json_attribute(GovernedAuditEvent.authority_scope)
freeze_json_attribute(GovernedAuditEvent.detail)
protect_immutable_model(GovernedAuditEvent)
event.listen(GovernedCommandReceipt, "before_update", _guard_command_receipt_update)
event.listen(GovernedCommandReceipt, "before_delete", _reject_delete)
