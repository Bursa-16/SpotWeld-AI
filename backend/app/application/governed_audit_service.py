"""Thin application service for transaction-participating governed audit."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from app.application.governed_unit_of_work import GovernedUnitOfWork
from app.models.governance import GovernedAuditEvent


class GovernedAuditService:
    """Construct audit events and persist them through the caller's unit of work."""

    def __init__(self, unit_of_work: GovernedUnitOfWork):
        self._unit_of_work = unit_of_work
        self._repository = unit_of_work.governance_repository

    def record_event(
        self,
        *,
        event_id: str,
        entity_type: str,
        entity_id: str,
        entity_revision: str,
        action: str,
        actor_id: str,
        actor_type: str,
        reason: str,
        correlation_id: str,
        schema_version: str,
        software_version: str,
        canonicalization_version: str,
        hash_algorithm: str,
        created_at: datetime,
        actor_user_id: int | None = None,
        actor_role: str | None = None,
        authority_scope: Mapping[str, object] | None = None,
        idempotency_key: str | None = None,
        prior_content_hash: str | None = None,
        new_content_hash: str | None = None,
        detail: Mapping[str, object] | None = None,
        correction_of_event_id: int | None = None,
    ) -> GovernedAuditEvent:
        """Persist one deterministic event inside the owning transaction."""
        self._unit_of_work.ensure_open()
        event = GovernedAuditEvent(
            event_id=event_id,
            entity_type=entity_type,
            entity_id=entity_id,
            entity_revision=entity_revision,
            action=action,
            actor_user_id=actor_user_id,
            actor_id=actor_id,
            actor_type=actor_type,
            actor_role=actor_role,
            authority_scope=(
                dict(authority_scope) if authority_scope is not None else None
            ),
            reason=reason,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            schema_version=schema_version,
            software_version=software_version,
            canonicalization_version=canonicalization_version,
            hash_algorithm=hash_algorithm,
            prior_content_hash=prior_content_hash,
            new_content_hash=new_content_hash,
            detail=dict(detail) if detail is not None else None,
            correction_of_event_id=correction_of_event_id,
            created_at=created_at,
        )
        return self._repository.add_event(event)
