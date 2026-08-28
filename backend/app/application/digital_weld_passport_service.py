"""Governed persistence for immutable Digital Weld Passport revisions."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import ClassVar

from sqlalchemy import select

from app.application.governed_audit_service import GovernedAuditService
from app.application.governed_idempotency_service import GovernedIdempotencyService
from app.application.governed_unit_of_work import GovernedUnitOfWork
from app.application.rule_registry_service import GovernedAuditMetadata
from app.domain.idempotency_types import (
    CanonicalRequestHash,
    CommandIdentity,
    CommandResultReference,
    IdempotencyDisposition,
)
from app.domain.readiness import ReadinessState
from app.models.digital_weld_passport import (
    DigitalWeldPassportLifecycleEvent,
    DigitalWeldPassportLifecycleState,
)
from app.models.entities import User
from app.models.machine_readiness import MachineReadinessAssessmentRevision
from app.models.rule_evaluation import RuleEvaluation
from app.repositories.digital_weld_passport_repository import (
    DigitalWeldPassportRepository,
)

__all__ = [
    "DigitalWeldPassportLifecycleTransitionDraft",
    "DigitalWeldPassportRevisionDraft",
    "DigitalWeldPassportService",
]


@dataclass(frozen=True, slots=True)
class DigitalWeldPassportRevisionDraft:
    """Immutable caller-pinned DWP revision payload."""

    passport_id: str
    revision_number: int
    context_snapshot: Mapping[str, object]
    provenance_snapshot: Mapping[str, object] = field(default_factory=dict)
    authority_snapshot: Mapping[str, object] = field(default_factory=dict)
    mrc_snapshot: Mapping[str, object] | None = None
    supersedes_revision_id: int | None = None

    def __post_init__(self) -> None:
        if not self.passport_id.strip():
            raise ValueError("passport_id must be a non-empty string")
        if self.revision_number <= 0:
            raise ValueError("revision_number must be positive")
        if not isinstance(self.context_snapshot, Mapping):
            raise TypeError("context_snapshot must be a mapping")
        if not isinstance(self.provenance_snapshot, Mapping):
            raise TypeError("provenance_snapshot must be a mapping")
        if not isinstance(self.authority_snapshot, Mapping):
            raise TypeError("authority_snapshot must be a mapping")
        if self.supersedes_revision_id is not None and self.supersedes_revision_id <= 0:
            raise ValueError("supersedes_revision_id must be positive")


@dataclass(frozen=True, slots=True)
class DigitalWeldPassportLifecycleTransitionDraft:
    """Append-only lifecycle transition for one exact DWP revision."""

    passport_id: str
    revision_number: int
    state: DigitalWeldPassportLifecycleState
    reason: str
    mrc_snapshot: Mapping[str, object] | None = None
    supersedes_lifecycle_event_id: int | None = None

    def __post_init__(self) -> None:
        if not self.passport_id.strip():
            raise ValueError("passport_id must be a non-empty string")
        if self.revision_number <= 0:
            raise ValueError("revision_number must be positive")
        if not self.reason.strip():
            raise ValueError("reason must be a non-empty string")
        if self.supersedes_lifecycle_event_id is not None and (
            self.supersedes_lifecycle_event_id <= 0
        ):
            raise ValueError("supersedes_lifecycle_event_id must be positive")


class DigitalWeldPassportService:
    """Persist governed DWP revisions without recomputing any engineering truth."""

    COMMAND_NAMESPACE = "dwp.passport"
    _FINALIZATION_STATES: ClassVar[set[DigitalWeldPassportLifecycleState]] = {
        DigitalWeldPassportLifecycleState.VALIDATED,
        DigitalWeldPassportLifecycleState.APPROVED,
        DigitalWeldPassportLifecycleState.PRODUCTION_ACTIVE,
    }
    _TERMINAL_STATES: ClassVar[set[DigitalWeldPassportLifecycleState]] = {
        DigitalWeldPassportLifecycleState.SUPERSEDED,
        DigitalWeldPassportLifecycleState.RETIRED,
        DigitalWeldPassportLifecycleState.ARCHIVED,
    }

    def __init__(self, unit_of_work: GovernedUnitOfWork):
        self._unit_of_work = unit_of_work
        self._repository = DigitalWeldPassportRepository(unit_of_work.session)
        self._idempotency = GovernedIdempotencyService(unit_of_work)
        self._audit = GovernedAuditService(unit_of_work)

    def create_draft_revision(
        self,
        *,
        draft: DigitalWeldPassportRevisionDraft,
        receipt_id: str,
        command_identity: CommandIdentity,
        request_hash: CanonicalRequestHash,
        audit: GovernedAuditMetadata,
        completed_at: datetime,
    ) -> CommandResultReference:
        self._unit_of_work.ensure_open()
        self._validate_command_identity(command_identity, draft.passport_id)
        decision = self._idempotency.reserve_or_inspect(
            receipt_id=receipt_id,
            identity=command_identity,
            request_hash=request_hash,
            correlation_id=audit.correlation_id,
            schema_version=audit.schema_version,
            software_version=audit.software_version,
            created_at=audit.created_at,
        )
        if decision.disposition is IdempotencyDisposition.REPLAY:
            if decision.result_reference is None:
                raise RuntimeError("completed DWP replay has no durable result")
            return decision.result_reference
        if decision.disposition is IdempotencyDisposition.CONFLICT:
            raise ValueError("idempotency conflict for DWP revision command")
        if decision.disposition is IdempotencyDisposition.IN_PROGRESS:
            raise RuntimeError("DWP revision command is already in progress")

        try:
            self._require_human_actor(audit)
            scope_snapshot = self._scope_snapshot(draft.context_snapshot)
            self._ensure_authority_scope_matches(audit, scope_snapshot)
            self._validate_context(draft=draft, scope_snapshot=scope_snapshot)
            if draft.mrc_snapshot is not None:
                self._validate_mrc_snapshot(
                    draft.mrc_snapshot,
                    required_state=None,
                    denial_code="MRC_SNAPSHOT_INVALID",
                )
            self._validate_provenance_snapshot(draft.provenance_snapshot)
        except ValueError as exc:
            return self._deny_command(
                entity_type="digital_weld_passport_revision",
                entity_id=draft.passport_id,
                entity_revision=str(draft.revision_number),
                action="PERSIST_DIGITAL_WELD_PASSPORT_REVISION_DENIED",
                audit=audit,
                completed_at=completed_at,
                command_identity=command_identity,
                request_hash=request_hash,
                denial_code="VALIDATION_ERROR",
                denial_reason=str(exc),
            )

        history = self._repository.list_history(draft.passport_id)
        if history:
            latest = history[-1]
            if draft.supersedes_revision_id != latest.id:
                return self._deny_command(
                    entity_type="digital_weld_passport_revision",
                    entity_id=draft.passport_id,
                    entity_revision=str(draft.revision_number),
                    action="PERSIST_DIGITAL_WELD_PASSPORT_REVISION_DENIED",
                    audit=audit,
                    completed_at=completed_at,
                    command_identity=command_identity,
                    request_hash=request_hash,
                    denial_code="BRANCHING_REVISION_REJECTED",
                    denial_reason=(
                        "passport corrections must supersede the current latest revision"
                    ),
                )
            if draft.revision_number != latest.revision_number + 1:
                return self._deny_command(
                    entity_type="digital_weld_passport_revision",
                    entity_id=draft.passport_id,
                    entity_revision=str(draft.revision_number),
                    action="PERSIST_DIGITAL_WELD_PASSPORT_REVISION_DENIED",
                    audit=audit,
                    completed_at=completed_at,
                    command_identity=command_identity,
                    request_hash=request_hash,
                    denial_code="REVISION_SEQUENCE_INVALID",
                    denial_reason="corrections must use the next revision_number",
                )
        else:
            if draft.supersedes_revision_id is not None or draft.revision_number != 1:
                return self._deny_command(
                    entity_type="digital_weld_passport_revision",
                    entity_id=draft.passport_id,
                    entity_revision=str(draft.revision_number),
                    action="PERSIST_DIGITAL_WELD_PASSPORT_REVISION_DENIED",
                    audit=audit,
                    completed_at=completed_at,
                    command_identity=command_identity,
                    request_hash=request_hash,
                    denial_code="REVISION_SEQUENCE_INVALID",
                    denial_reason="first passport revision_number must be 1",
                )

        passport = self._repository.get_by_passport_id(draft.passport_id)
        if passport is None:
            passport = self._repository.create_passport(
                passport_id=draft.passport_id,
                created_by_actor_id=audit.actor_id,
                created_by_user_id=audit.actor_user_id,
            )

        authority_snapshot = self._revision_authority_snapshot(
            audit=audit,
            draft=draft,
            scope_snapshot=scope_snapshot,
            created_at=completed_at,
        )
        content_hash = self._hash(
            {
                "passport_id": draft.passport_id,
                "revision_number": draft.revision_number,
                "context_snapshot": scope_snapshot,
                "mrc_snapshot": self._canonicalize(draft.mrc_snapshot),
                "provenance_snapshot": self._canonicalize(draft.provenance_snapshot),
                "authority_snapshot": authority_snapshot,
                "supersedes_revision_id": draft.supersedes_revision_id,
            }
        )
        revision = self._repository.create_revision(
            passport=passport,
            revision_number=draft.revision_number,
            context_snapshot=dict(draft.context_snapshot),
            mrc_snapshot=(
                dict(draft.mrc_snapshot) if draft.mrc_snapshot is not None else None
            ),
            provenance_snapshot=dict(draft.provenance_snapshot),
            authority_snapshot=authority_snapshot,
            created_by_actor_id=audit.actor_id,
            created_by_user_id=audit.actor_user_id,
            schema_version=audit.schema_version,
            canonicalization_version=audit.canonicalization_version,
            hash_algorithm=audit.hash_algorithm,
            content_hash=content_hash,
            software_version=audit.software_version,
            correlation_id=audit.correlation_id,
            supersedes_revision_id=draft.supersedes_revision_id,
        )
        lifecycle_event = self._repository.create_lifecycle_event(
            passport_revision=revision,
            revision_number=1,
            state=DigitalWeldPassportLifecycleState.DRAFT,
            authority_snapshot=authority_snapshot,
            reason=audit.reason,
            created_by_actor_id=audit.actor_id,
            created_by_user_id=audit.actor_user_id,
            schema_version=audit.schema_version,
            canonicalization_version=audit.canonicalization_version,
            hash_algorithm=audit.hash_algorithm,
            content_hash=self._hash(
                {
                    "passport_id": draft.passport_id,
                    "revision_number": draft.revision_number,
                    "state": DigitalWeldPassportLifecycleState.DRAFT.value,
                    "authority_snapshot": authority_snapshot,
                    "reason": audit.reason,
                }
            ),
            software_version=audit.software_version,
            correlation_id=audit.correlation_id,
        )
        self._audit.record_event(
            **self._common_audit_fields(audit),
            entity_type="digital_weld_passport_revision",
            entity_id=draft.passport_id,
            entity_revision=str(draft.revision_number),
            action=(
                "CORRECT_DIGITAL_WELD_PASSPORT_REVISION"
                if draft.supersedes_revision_id is not None
                else "PERSIST_DIGITAL_WELD_PASSPORT_REVISION"
            ),
            prior_content_hash=(
                None if draft.supersedes_revision_id is None else history[-1].content_hash
            ),
            new_content_hash=content_hash,
            detail=self._audit_detail(
                audit,
                command=(
                    "CORRECT_DIGITAL_WELD_PASSPORT_REVISION"
                    if draft.supersedes_revision_id is not None
                    else "PERSIST_DIGITAL_WELD_PASSPORT_REVISION"
                ),
                passport_id=draft.passport_id,
                revision_number=draft.revision_number,
                supersedes_revision_id=draft.supersedes_revision_id,
                lifecycle_event_id=lifecycle_event.id,
                context_snapshot=scope_snapshot,
            ),
        )
        result = CommandResultReference(
            result_type="digital_weld_passport",
            result_id=draft.passport_id,
            result_revision=str(draft.revision_number),
        )
        completed = self._idempotency.complete(
            identity=command_identity,
            request_hash=request_hash,
            result_reference=result,
            completed_at=completed_at,
        )
        if completed.result_reference != result:
            raise RuntimeError("DWP revision idempotency completion failed")
        return result

    def transition_revision(
        self,
        *,
        transition: DigitalWeldPassportLifecycleTransitionDraft,
        receipt_id: str,
        command_identity: CommandIdentity,
        request_hash: CanonicalRequestHash,
        audit: GovernedAuditMetadata,
        completed_at: datetime,
    ) -> CommandResultReference:
        self._unit_of_work.ensure_open()
        self._validate_command_identity(command_identity, transition.passport_id)
        decision = self._idempotency.reserve_or_inspect(
            receipt_id=receipt_id,
            identity=command_identity,
            request_hash=request_hash,
            correlation_id=audit.correlation_id,
            schema_version=audit.schema_version,
            software_version=audit.software_version,
            created_at=audit.created_at,
        )
        if decision.disposition is IdempotencyDisposition.REPLAY:
            if decision.result_reference is None:
                raise RuntimeError("completed DWP replay has no durable result")
            return decision.result_reference
        if decision.disposition is IdempotencyDisposition.CONFLICT:
            raise ValueError("idempotency conflict for DWP lifecycle command")
        if decision.disposition is IdempotencyDisposition.IN_PROGRESS:
            raise RuntimeError("DWP lifecycle command is already in progress")

        try:
            actor = self._require_human_actor(audit)
            passport = self._repository.get_by_passport_id(transition.passport_id)
            if passport is None:
                return self._deny_command(
                    entity_type="digital_weld_passport_lifecycle_event",
                    entity_id=transition.passport_id,
                    entity_revision=str(transition.revision_number),
                    action="APPEND_DIGITAL_WELD_PASSPORT_LIFECYCLE_EVENT_DENIED",
                    audit=audit,
                    completed_at=completed_at,
                    command_identity=command_identity,
                    request_hash=request_hash,
                    denial_code="MISSING_PASSPORT_IDENTITY",
                    denial_reason="passport identity does not exist",
                )

            revision = self._repository.get_revision(
                transition.passport_id,
                transition.revision_number,
            )
            if revision is None:
                return self._deny_command(
                    entity_type="digital_weld_passport_lifecycle_event",
                    entity_id=transition.passport_id,
                    entity_revision=str(transition.revision_number),
                    action="APPEND_DIGITAL_WELD_PASSPORT_LIFECYCLE_EVENT_DENIED",
                    audit=audit,
                    completed_at=completed_at,
                    command_identity=command_identity,
                    request_hash=request_hash,
                    denial_code="MISSING_PASSPORT_REVISION",
                    denial_reason="passport revision does not exist",
                )

            scope_snapshot = self._scope_snapshot(revision.context_snapshot)
            self._ensure_authority_scope_matches(audit, scope_snapshot)
            self._validate_context(
                draft=DigitalWeldPassportRevisionDraft(
                    passport_id=revision.passport_id,
                    revision_number=revision.revision_number,
                    context_snapshot=revision.context_snapshot,
                    provenance_snapshot=revision.provenance_snapshot,
                    authority_snapshot=revision.authority_snapshot,
                    mrc_snapshot=revision.mrc_snapshot,
                    supersedes_revision_id=revision.supersedes_revision_id,
                ),
                scope_snapshot=scope_snapshot,
            )
        except ValueError as exc:
            return self._deny_command(
                entity_type="digital_weld_passport_lifecycle_event",
                entity_id=transition.passport_id,
                entity_revision=str(transition.revision_number),
                action="APPEND_DIGITAL_WELD_PASSPORT_LIFECYCLE_EVENT_DENIED",
                audit=audit,
                completed_at=completed_at,
                command_identity=command_identity,
                request_hash=request_hash,
                denial_code="VALIDATION_ERROR",
                denial_reason=str(exc),
            )

        history = self._repository.list_lifecycle_history(revision.id)
        current = history[-1] if history else None
        if current is None:
            return self._deny_command(
                entity_type="digital_weld_passport_lifecycle_event",
                entity_id=transition.passport_id,
                entity_revision=str(transition.revision_number),
                action="APPEND_DIGITAL_WELD_PASSPORT_LIFECYCLE_EVENT_DENIED",
                audit=audit,
                completed_at=completed_at,
                command_identity=command_identity,
                request_hash=request_hash,
                denial_code="MISSING_INITIAL_LIFECYCLE_EVENT",
                denial_reason="passport revision has no initial lifecycle event",
            )

        if transition.supersedes_lifecycle_event_id != current.id:
            return self._deny_command(
                entity_type="digital_weld_passport_lifecycle_event",
                entity_id=transition.passport_id,
                entity_revision=str(transition.revision_number),
                action="APPEND_DIGITAL_WELD_PASSPORT_LIFECYCLE_EVENT_DENIED",
                audit=audit,
                completed_at=completed_at,
                command_identity=command_identity,
                request_hash=request_hash,
                denial_code="BRANCHING_LIFECYCLE_EVENT_REJECTED",
                denial_reason=(
                    "passport lifecycle events must supersede the current latest event"
                ),
            )

        if not self._transition_allowed(current.state, transition.state):
            return self._deny_command(
                entity_type="digital_weld_passport_lifecycle_event",
                entity_id=transition.passport_id,
                entity_revision=str(transition.revision_number),
                action="APPEND_DIGITAL_WELD_PASSPORT_LIFECYCLE_EVENT_DENIED",
                audit=audit,
                completed_at=completed_at,
                command_identity=command_identity,
                request_hash=request_hash,
                denial_code="INVALID_LIFECYCLE_TRANSITION",
                denial_reason=(
                    f"cannot transition from {current.state.value} to {transition.state.value}"
                ),
            )

        mrc_snapshot = (
            dict(transition.mrc_snapshot)
            if transition.mrc_snapshot is not None
            else dict(revision.mrc_snapshot)
            if revision.mrc_snapshot is not None
            else None
        )
        if transition.state in self._FINALIZATION_STATES:
            if mrc_snapshot is None:
                return self._deny_command(
                    entity_type="digital_weld_passport_lifecycle_event",
                    entity_id=transition.passport_id,
                    entity_revision=str(transition.revision_number),
                    action="APPEND_DIGITAL_WELD_PASSPORT_LIFECYCLE_EVENT_DENIED",
                    audit=audit,
                    completed_at=completed_at,
                    command_identity=command_identity,
                    request_hash=request_hash,
                    denial_code="MISSING_READY_MRC_REFERENCE",
                    denial_reason="finalized passport states require an exact READY MRC reference",
                )
            try:
                mrc_row = self._validate_mrc_snapshot(
                    mrc_snapshot,
                    required_state=ReadinessState.READY,
                    denial_code="MRC_NOT_READY",
                )
            except ValueError as exc:
                return self._deny_command(
                    entity_type="digital_weld_passport_lifecycle_event",
                    entity_id=transition.passport_id,
                    entity_revision=str(transition.revision_number),
                    action="APPEND_DIGITAL_WELD_PASSPORT_LIFECYCLE_EVENT_DENIED",
                    audit=audit,
                    completed_at=completed_at,
                    command_identity=command_identity,
                    request_hash=request_hash,
                    denial_code="VALIDATION_ERROR",
                    denial_reason=str(exc),
                )
            if mrc_row is None:
                return self._deny_command(
                    entity_type="digital_weld_passport_lifecycle_event",
                    entity_id=transition.passport_id,
                    entity_revision=str(transition.revision_number),
                    action="APPEND_DIGITAL_WELD_PASSPORT_LIFECYCLE_EVENT_DENIED",
                    audit=audit,
                    completed_at=completed_at,
                    command_identity=command_identity,
                    request_hash=request_hash,
                    denial_code="MRC_NOT_READY",
                    denial_reason="finalized passport states require a READY MRC revision",
                )

        if transition.state in {
            DigitalWeldPassportLifecycleState.VALIDATED,
            DigitalWeldPassportLifecycleState.APPROVED,
            DigitalWeldPassportLifecycleState.PRODUCTION_ACTIVE,
        }:
            if revision.created_by_user_id is not None and revision.created_by_user_id == actor.id:
                return self._deny_command(
                    entity_type="digital_weld_passport_lifecycle_event",
                    entity_id=transition.passport_id,
                    entity_revision=str(transition.revision_number),
                    action="APPEND_DIGITAL_WELD_PASSPORT_LIFECYCLE_EVENT_DENIED",
                    audit=audit,
                    completed_at=completed_at,
                    command_identity=command_identity,
                    request_hash=request_hash,
                    denial_code="SEPARATION_OF_DUTIES_VIOLATION",
                    denial_reason="finalization authority must differ from draft creation authority",
                )
            if (
                transition.state in {
                    DigitalWeldPassportLifecycleState.APPROVED,
                    DigitalWeldPassportLifecycleState.PRODUCTION_ACTIVE,
                }
                and current.created_by_user_id is not None
                and current.created_by_user_id == actor.id
            ):
                return self._deny_command(
                    entity_type="digital_weld_passport_lifecycle_event",
                    entity_id=transition.passport_id,
                    entity_revision=str(transition.revision_number),
                    action="APPEND_DIGITAL_WELD_PASSPORT_LIFECYCLE_EVENT_DENIED",
                    audit=audit,
                    completed_at=completed_at,
                    command_identity=command_identity,
                    request_hash=request_hash,
                    denial_code="SEPARATION_OF_DUTIES_VIOLATION",
                    denial_reason="approval/release authority must differ from prior lifecycle authority",
                )
            if (
                transition.state is DigitalWeldPassportLifecycleState.PRODUCTION_ACTIVE
                and current.state is not DigitalWeldPassportLifecycleState.APPROVED
            ):
                return self._deny_command(
                    entity_type="digital_weld_passport_lifecycle_event",
                    entity_id=transition.passport_id,
                    entity_revision=str(transition.revision_number),
                    action="APPEND_DIGITAL_WELD_PASSPORT_LIFECYCLE_EVENT_DENIED",
                    audit=audit,
                    completed_at=completed_at,
                    command_identity=command_identity,
                    request_hash=request_hash,
                    denial_code="MISSING_APPROVAL_PRECONDITION",
                    denial_reason="production activation requires an approved revision",
                )

        authority_snapshot = self._transition_authority_snapshot(
            audit=audit,
            transition=transition,
            scope_snapshot=scope_snapshot,
            mrc_snapshot=mrc_snapshot,
            completed_at=completed_at,
            prior_event=current,
        )
        transition_content_hash = self._hash(
            {
                "passport_id": transition.passport_id,
                "revision_number": transition.revision_number,
                "state": transition.state.value,
                "reason": transition.reason,
                "scope_snapshot": scope_snapshot,
                "authority_snapshot": authority_snapshot,
                "mrc_snapshot": self._canonicalize(mrc_snapshot),
                "prior_lifecycle_event_id": current.id,
                "supersedes_lifecycle_event_id": transition.supersedes_lifecycle_event_id,
            }
        )
        lifecycle_event = self._repository.create_lifecycle_event(
            passport_revision=revision,
            revision_number=current.revision_number + 1,
            state=transition.state,
            authority_snapshot=authority_snapshot,
            reason=transition.reason,
            created_by_actor_id=audit.actor_id,
            created_by_user_id=audit.actor_user_id,
            schema_version=audit.schema_version,
            canonicalization_version=audit.canonicalization_version,
            hash_algorithm=audit.hash_algorithm,
            content_hash=transition_content_hash,
            software_version=audit.software_version,
            correlation_id=audit.correlation_id,
            supersedes_lifecycle_event_id=current.id,
            prior_content_hash=current.content_hash,
            new_content_hash=transition_content_hash,
        )
        self._audit.record_event(
            **self._common_audit_fields(audit),
            entity_type="digital_weld_passport_lifecycle_event",
            entity_id=transition.passport_id,
            entity_revision=str(transition.revision_number),
            action="APPEND_DIGITAL_WELD_PASSPORT_LIFECYCLE_EVENT",
            prior_content_hash=current.content_hash,
            new_content_hash=lifecycle_event.content_hash,
            detail=self._audit_detail(
                audit,
                command="APPEND_DIGITAL_WELD_PASSPORT_LIFECYCLE_EVENT",
                passport_id=transition.passport_id,
                revision_number=transition.revision_number,
                lifecycle_event_id=lifecycle_event.id,
                state=transition.state.value,
                reason=transition.reason,
                mrc_snapshot=self._canonicalize(mrc_snapshot),
            ),
        )
        result = CommandResultReference(
            result_type="digital_weld_passport",
            result_id=transition.passport_id,
            result_revision=str(transition.revision_number),
        )
        completed = self._idempotency.complete(
            identity=command_identity,
            request_hash=request_hash,
            result_reference=result,
            completed_at=completed_at,
        )
        if completed.result_reference != result:
            raise RuntimeError("DWP lifecycle idempotency completion failed")
        return result

    def _validate_command_identity(
        self,
        command_identity: CommandIdentity,
        passport_id: str,
    ) -> None:
        if command_identity.command_namespace != self.COMMAND_NAMESPACE:
            raise ValueError("DWP command namespace mismatch")
        if command_identity.command_scope != passport_id:
            raise ValueError("DWP command scope must match passport_id")

    def _require_human_actor(self, audit: GovernedAuditMetadata) -> User:
        if audit.actor_type != "user" or audit.actor_user_id is None:
            raise ValueError("DWP commands require a durable human user actor")
        actor = self._repository.session.get(User, audit.actor_user_id)
        if actor is None or not actor.is_active:
            raise ValueError("DWP commands require an active user actor")
        return actor

    @staticmethod
    def _scope_snapshot(context_snapshot: Mapping[str, object]) -> dict[str, object]:
        scope_snapshot = context_snapshot.get("scope_snapshot")
        if not isinstance(scope_snapshot, Mapping):
            raise TypeError("context_snapshot must include a scope_snapshot mapping")
        scope = dict(scope_snapshot)
        if not scope:
            raise ValueError("scope_snapshot must not be empty")
        return scope

    def _ensure_authority_scope_matches(
        self,
        audit: GovernedAuditMetadata,
        scope_snapshot: Mapping[str, object],
    ) -> None:
        if audit.authority_scope is None:
            raise ValueError("DWP commands require an explicit authority scope")
        if self._canonicalize(audit.authority_scope) != self._canonicalize(scope_snapshot):
            raise ValueError("authority scope must match the governed passport scope")

    def _validate_context(
        self,
        *,
        draft: DigitalWeldPassportRevisionDraft,
        scope_snapshot: Mapping[str, object],
    ) -> None:
        passport_id = draft.context_snapshot.get("passport_id")
        if passport_id != draft.passport_id:
            raise ValueError("context_snapshot passport_id must match the draft passport_id")
        if self._scope_snapshot(draft.context_snapshot) != dict(scope_snapshot):
            raise ValueError("context_snapshot scope_snapshot must match the governed scope")

    def _validate_mrc_snapshot(
        self,
        mrc_snapshot: Mapping[str, object],
        *,
        required_state: ReadinessState | None,
        denial_code: str,
    ) -> MachineReadinessAssessmentRevision | None:
        if not isinstance(mrc_snapshot, Mapping):
            raise TypeError("mrc_snapshot must be a mapping")
        assessment_id = mrc_snapshot.get("assessment_id")
        revision_number = mrc_snapshot.get("revision_number")
        if not isinstance(assessment_id, str) or not assessment_id.strip():
            raise ValueError("mrc_snapshot must include an assessment_id")
        if not isinstance(revision_number, int) or isinstance(revision_number, bool):
            raise TypeError("mrc_snapshot must include an integer revision_number")
        statement = select(MachineReadinessAssessmentRevision).where(
            MachineReadinessAssessmentRevision.assessment_id == assessment_id,
            MachineReadinessAssessmentRevision.revision_number == revision_number,
        )
        row = self._repository.session.scalar(statement)
        if row is None:
            raise ValueError("pinned MRC revision does not exist")
        expected = self._mrc_snapshot(row)
        if self._canonicalize(mrc_snapshot) != self._canonicalize(expected):
            raise ValueError("pinned MRC snapshot must exactly match the stored revision")
        if required_state is not None and row.state is not required_state:
            return None
        return row

    def _validate_provenance_snapshot(self, provenance_snapshot: Mapping[str, object]) -> None:
        if not isinstance(provenance_snapshot, Mapping):
            raise TypeError("provenance_snapshot must be a mapping")
        rule_evaluations = provenance_snapshot.get("rule_evaluations")
        if rule_evaluations is None:
            return
        if not isinstance(rule_evaluations, Sequence) or isinstance(rule_evaluations, (str, bytes)):
            raise TypeError("provenance_snapshot.rule_evaluations must be a sequence")
        for entry in rule_evaluations:
            if not isinstance(entry, Mapping):
                raise TypeError("rule_evaluation provenance entries must be mappings")
            evaluation_id = entry.get("evaluation_id")
            revision_number = entry.get("revision_number")
            if not isinstance(evaluation_id, str) or not evaluation_id.strip():
                raise ValueError("rule_evaluation entries require evaluation_id")
            if not isinstance(revision_number, int) or isinstance(revision_number, bool):
                raise TypeError("rule_evaluation entries require revision_number")
            row = self._repository.session.scalar(
                select(RuleEvaluation).where(
                    RuleEvaluation.evaluation_id == evaluation_id,
                    RuleEvaluation.revision_number == revision_number,
                )
            )
            if row is None:
                raise ValueError("pinned rule evaluation revision does not exist")
            expected = self._rule_evaluation_snapshot(row)
            if self._canonicalize(entry) != self._canonicalize(expected):
                raise ValueError(
                    "pinned rule evaluation snapshot must exactly match the stored revision"
                )

    def _deny_command(
        self,
        *,
        entity_type: str,
        entity_id: str,
        entity_revision: str,
        action: str,
        audit: GovernedAuditMetadata,
        completed_at: datetime,
        command_identity: CommandIdentity,
        request_hash: CanonicalRequestHash,
        denial_code: str,
        denial_reason: str,
    ) -> CommandResultReference:
        denial_event = self._audit.record_event(
            **self._common_audit_fields(audit),
            entity_type=f"{entity_type}_denial",
            entity_id=entity_id,
            entity_revision=entity_revision,
            action=action,
            prior_content_hash=None,
            new_content_hash=None,
            detail=self._audit_detail(
                audit,
                command=action,
                entity_type=entity_type,
                entity_id=entity_id,
                entity_revision=entity_revision,
                denial_code=denial_code,
                denial_reason=denial_reason,
            ),
        )
        result = CommandResultReference(
            result_type="digital_weld_passport_denial",
            result_id=str(denial_event.id),
            result_revision="denied",
        )
        completed = self._idempotency.complete(
            identity=command_identity,
            request_hash=request_hash,
            result_reference=result,
            completed_at=completed_at,
        )
        if completed.result_reference != result:
            raise RuntimeError("DWP denial idempotency completion failed")
        return result

    def _transition_allowed(
        self,
        current: DigitalWeldPassportLifecycleState,
        target: DigitalWeldPassportLifecycleState,
    ) -> bool:
        if target is DigitalWeldPassportLifecycleState.DRAFT:
            return False
        terminal = self._TERMINAL_STATES
        if current is DigitalWeldPassportLifecycleState.DRAFT:
            return target in {
                DigitalWeldPassportLifecycleState.ENGINEERING_DEFINED,
                DigitalWeldPassportLifecycleState.VALIDATED,
            }
        if current is DigitalWeldPassportLifecycleState.ENGINEERING_DEFINED:
            return target in {
                DigitalWeldPassportLifecycleState.VALIDATION_PENDING,
                *terminal,
            }
        if current is DigitalWeldPassportLifecycleState.VALIDATION_PENDING:
            return target in {
                DigitalWeldPassportLifecycleState.VALIDATED,
                *terminal,
            }
        if current is DigitalWeldPassportLifecycleState.VALIDATED:
            return target in {
                DigitalWeldPassportLifecycleState.APPROVED,
                *terminal,
            }
        if current is DigitalWeldPassportLifecycleState.APPROVED:
            return target in {
                DigitalWeldPassportLifecycleState.PRODUCTION_ACTIVE,
                *terminal,
            }
        if current is DigitalWeldPassportLifecycleState.PRODUCTION_ACTIVE:
            return target in terminal
        return False

    def _revision_authority_snapshot(
        self,
        *,
        audit: GovernedAuditMetadata,
        draft: DigitalWeldPassportRevisionDraft,
        scope_snapshot: Mapping[str, object],
        created_at: datetime,
    ) -> dict[str, object]:
        return {
            "passport_id": draft.passport_id,
            "revision_number": draft.revision_number,
            "scope_snapshot": dict(scope_snapshot),
            "actor_id": audit.actor_id,
            "actor_user_id": audit.actor_user_id,
            "actor_type": audit.actor_type,
            "actor_role": audit.actor_role,
            "reason": audit.reason,
            "correlation_id": audit.correlation_id,
            "created_at": created_at.isoformat(),
            "supersedes_revision_id": draft.supersedes_revision_id,
            "policy_identifier": "SDS-113",
            "policy_version": "0.1 Draft",
        }

    def _transition_authority_snapshot(
        self,
        *,
        audit: GovernedAuditMetadata,
        transition: DigitalWeldPassportLifecycleTransitionDraft,
        scope_snapshot: Mapping[str, object],
        mrc_snapshot: Mapping[str, object] | None,
        completed_at: datetime,
        prior_event: DigitalWeldPassportLifecycleEvent,
    ) -> dict[str, object]:
        return {
            "passport_id": transition.passport_id,
            "revision_number": transition.revision_number,
            "scope_snapshot": dict(scope_snapshot),
            "target_state": transition.state.value,
            "actor_id": audit.actor_id,
            "actor_user_id": audit.actor_user_id,
            "actor_type": audit.actor_type,
            "actor_role": audit.actor_role,
            "reason": transition.reason,
            "correlation_id": audit.correlation_id,
            "decision_at": completed_at.isoformat(),
            "prior_lifecycle_event_id": prior_event.id,
            "prior_lifecycle_event_state": prior_event.state.value,
            "mrc_snapshot": self._canonicalize(mrc_snapshot),
            "policy_identifier": "SDS-113",
            "policy_version": "0.1 Draft",
        }

    @staticmethod
    def _mrc_snapshot(row: MachineReadinessAssessmentRevision) -> dict[str, object]:
        return {
            "assessment_id": row.assessment_id,
            "revision_number": row.revision_number,
            "decision_time": row.decision_time.isoformat(),
            "state": row.state.value,
            "context_snapshot": row.context_snapshot,
            "prerequisites_snapshot": row.prerequisites_snapshot,
            "result_snapshot": row.result_snapshot,
            "authority_snapshot": row.authority_snapshot,
            "validated_applicable_basis_count": row.validated_applicable_basis_count,
            "supersedes_assessment_revision_id": row.supersedes_assessment_revision_id,
            "created_by_user_id": row.created_by_user_id,
            "created_by_actor_id": row.created_by_actor_id,
            "schema_version": row.schema_version,
            "canonicalization_version": row.canonicalization_version,
            "hash_algorithm": row.hash_algorithm,
            "content_hash": row.content_hash,
            "software_version": row.software_version,
            "correlation_id": row.correlation_id,
        }

    @staticmethod
    def _rule_evaluation_snapshot(row: RuleEvaluation) -> dict[str, object]:
        return {
            "evaluation_id": row.evaluation_id,
            "revision_number": row.revision_number,
            "engineering_rule_id": row.engineering_rule_id,
            "engineering_rule_revision_id": row.engineering_rule_revision_id,
            "rule_id": row.rule_id,
            "rule_revision": row.rule_revision,
            "parameter": row.parameter,
            "operator": row.operator.value,
            "outcome": row.outcome.value,
            "reason": row.reason,
            "decision_time": row.decision_time.isoformat(),
            "observed_value": row.observed_value,
            "observed_unit": row.observed_unit,
            "compared_value": row.compared_value,
            "applicability_snapshot": row.applicability_snapshot,
            "observation_snapshot": row.observation_snapshot,
            "unit_policy_snapshot": row.unit_policy_snapshot,
            "result_snapshot": row.result_snapshot,
            "authority_snapshot": row.authority_snapshot,
            "supersedes_evaluation_id": row.supersedes_evaluation_id,
            "created_by_user_id": row.created_by_user_id,
            "created_by_actor_id": row.created_by_actor_id,
            "schema_version": row.schema_version,
            "canonicalization_version": row.canonicalization_version,
            "hash_algorithm": row.hash_algorithm,
            "content_hash": row.content_hash,
            "software_version": row.software_version,
            "correlation_id": row.correlation_id,
        }

    @staticmethod
    def _common_audit_fields(audit: GovernedAuditMetadata) -> dict[str, object]:
        return {
            "event_id": audit.event_id,
            "actor_id": audit.actor_id,
            "actor_type": audit.actor_type,
            "reason": audit.reason,
            "correlation_id": audit.correlation_id,
            "schema_version": audit.schema_version,
            "software_version": audit.software_version,
            "canonicalization_version": audit.canonicalization_version,
            "hash_algorithm": audit.hash_algorithm,
            "created_at": audit.created_at,
            "actor_user_id": audit.actor_user_id,
            "actor_role": audit.actor_role,
            "authority_scope": audit.authority_scope,
            "idempotency_key": audit.idempotency_key,
        }

    @staticmethod
    def _audit_detail(
        audit: GovernedAuditMetadata,
        **command_detail: object,
    ) -> dict[str, object]:
        detail = dict(audit.detail) if audit.detail is not None else {}
        detail.update(command_detail)
        return detail

    @staticmethod
    def _hash(value: object) -> str:
        payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @classmethod
    def _canonicalize(cls, value: object) -> object:
        if isinstance(value, Mapping):
            return {key: cls._canonicalize(inner) for key, inner in sorted(value.items())}
        if isinstance(value, list):
            return [cls._canonicalize(item) for item in value]
        if isinstance(value, tuple):
            return [cls._canonicalize(item) for item in value]
        return value
