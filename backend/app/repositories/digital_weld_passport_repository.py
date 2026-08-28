from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.digital_weld_passport import (
    DigitalWeldPassport,
    DigitalWeldPassportLifecycleEvent,
    DigitalWeldPassportLifecycleState,
    DigitalWeldPassportRevision,
)


class DigitalWeldPassportRepository:
    """Append-only DWP persistence under a caller-owned transaction."""

    def __init__(self, session: Session):
        self.session = session

    def get_by_passport_id(self, passport_id: str) -> DigitalWeldPassport | None:
        return self.session.scalar(
            select(DigitalWeldPassport).where(
                DigitalWeldPassport.passport_id == passport_id
            )
        )

    def create_passport(
        self,
        *,
        passport_id: str,
        created_by_actor_id: str,
        created_by_user_id: int | None = None,
    ) -> DigitalWeldPassport:
        passport = DigitalWeldPassport(
            passport_id=passport_id,
            created_by_user_id=created_by_user_id,
            created_by_actor_id=created_by_actor_id,
        )
        self.session.add(passport)
        self.session.flush()
        self.session.refresh(passport)
        return passport

    def list_history(self, passport_id: str) -> list[DigitalWeldPassportRevision]:
        statement = (
            select(DigitalWeldPassportRevision)
            .where(DigitalWeldPassportRevision.passport_id == passport_id)
            .order_by(
                DigitalWeldPassportRevision.revision_number,
                DigitalWeldPassportRevision.id,
            )
        )
        return list(self.session.scalars(statement))

    def get_revision(
        self,
        passport_id: str,
        revision_number: int,
    ) -> DigitalWeldPassportRevision | None:
        statement = (
            select(DigitalWeldPassportRevision)
            .where(
                DigitalWeldPassportRevision.passport_id == passport_id,
                DigitalWeldPassportRevision.revision_number == revision_number,
            )
        )
        return self.session.scalar(statement)

    def create_revision(
        self,
        *,
        passport: DigitalWeldPassport,
        revision_number: int,
        context_snapshot: dict[str, object],
        mrc_snapshot: dict[str, object] | None,
        provenance_snapshot: dict[str, object],
        authority_snapshot: dict[str, object],
        created_by_actor_id: str,
        created_by_user_id: int | None,
        schema_version: str,
        canonicalization_version: str,
        hash_algorithm: str,
        content_hash: str,
        software_version: str,
        correlation_id: str,
        supersedes_revision_id: int | None = None,
    ) -> DigitalWeldPassportRevision:
        if not passport.passport_id.strip():
            raise ValueError("digital weld passport must have an identity")
        if revision_number <= 0:
            raise ValueError("passport revision_number must be positive")

        history = self.list_history(passport.passport_id)
        if supersedes_revision_id is None:
            if history:
                raise ValueError(
                    "existing passport identity requires an explicit prior revision"
                )
            if revision_number != 1:
                raise ValueError("first passport revision_number must be 1")
        else:
            prior = self.session.get(
                DigitalWeldPassportRevision, supersedes_revision_id
            )
            if prior is None:
                raise ValueError("superseded passport revision does not exist")
            if prior.passport_id != passport.passport_id:
                raise ValueError("passport correction cannot cross passport identities")
            if revision_number != prior.revision_number + 1:
                raise ValueError("passport correction must use the next revision_number")
            if any(item.supersedes_revision_id == prior.id for item in history):
                raise ValueError("passport revision already has a successor")

        revision = DigitalWeldPassportRevision(
            passport_id=passport.passport_id,
            revision_number=revision_number,
            context_snapshot=context_snapshot,
            mrc_snapshot=mrc_snapshot,
            provenance_snapshot=provenance_snapshot,
            authority_snapshot=authority_snapshot,
            supersedes_revision_id=supersedes_revision_id,
            created_by_user_id=created_by_user_id,
            created_by_actor_id=created_by_actor_id,
            schema_version=schema_version,
            canonicalization_version=canonicalization_version,
            hash_algorithm=hash_algorithm,
            content_hash=content_hash,
            software_version=software_version,
            correlation_id=correlation_id,
        )
        self.session.add(revision)
        self.session.flush()
        self.session.refresh(revision)

        managed_passport = (
            self.session.get(DigitalWeldPassport, passport.id)
            if passport.id is not None
            else None
        )
        if managed_passport is not None:
            managed_passport.current_revision_id = revision.id
            self.session.flush()
        return revision

    def list_lifecycle_history(
        self,
        passport_revision_id: int,
    ) -> list[DigitalWeldPassportLifecycleEvent]:
        statement = (
            select(DigitalWeldPassportLifecycleEvent)
            .where(
                DigitalWeldPassportLifecycleEvent.passport_revision_id
                == passport_revision_id
            )
            .order_by(
                DigitalWeldPassportLifecycleEvent.revision_number,
                DigitalWeldPassportLifecycleEvent.id,
            )
        )
        return list(self.session.scalars(statement))

    def get_current_lifecycle_event(
        self,
        passport_revision_id: int,
    ) -> DigitalWeldPassportLifecycleEvent | None:
        history = self.list_lifecycle_history(passport_revision_id)
        return history[-1] if history else None

    def create_lifecycle_event(
        self,
        *,
        passport_revision: DigitalWeldPassportRevision,
        revision_number: int,
        state: DigitalWeldPassportLifecycleState,
        authority_snapshot: dict[str, object],
        reason: str,
        created_by_actor_id: str,
        created_by_user_id: int | None,
        schema_version: str,
        canonicalization_version: str,
        hash_algorithm: str,
        content_hash: str,
        software_version: str,
        correlation_id: str,
        supersedes_lifecycle_event_id: int | None = None,
        prior_content_hash: str | None = None,
        new_content_hash: str | None = None,
    ) -> DigitalWeldPassportLifecycleEvent:
        if passport_revision.id is None:
            raise ValueError("passport revision must have a database identity")
        if revision_number <= 0:
            raise ValueError("lifecycle event revision_number must be positive")

        history = self.list_lifecycle_history(passport_revision.id)
        if supersedes_lifecycle_event_id is None:
            if history:
                raise ValueError(
                    "existing lifecycle event identity requires an explicit prior revision"
                )
            if revision_number != 1:
                raise ValueError("first lifecycle event revision_number must be 1")
        else:
            prior = self.session.get(
                DigitalWeldPassportLifecycleEvent, supersedes_lifecycle_event_id
            )
            if prior is None:
                raise ValueError("superseded lifecycle event does not exist")
            if prior.passport_revision_id != passport_revision.id:
                raise ValueError(
                    "lifecycle event supersession must remain within the same revision"
                )
            if revision_number != prior.revision_number + 1:
                raise ValueError(
                    "lifecycle event correction must use the next revision_number"
                )
            if any(item.supersedes_lifecycle_event_id == prior.id for item in history):
                raise ValueError("lifecycle event already has a successor")

        lifecycle_event = DigitalWeldPassportLifecycleEvent(
            passport_revision_id=passport_revision.id,
            revision_number=revision_number,
            state=state,
            authority_snapshot=authority_snapshot,
            reason=reason,
            prior_content_hash=prior_content_hash,
            new_content_hash=new_content_hash,
            supersedes_lifecycle_event_id=supersedes_lifecycle_event_id,
            created_by_user_id=created_by_user_id,
            created_by_actor_id=created_by_actor_id,
            schema_version=schema_version,
            canonicalization_version=canonicalization_version,
            hash_algorithm=hash_algorithm,
            content_hash=content_hash,
            software_version=software_version,
            correlation_id=correlation_id,
        )
        self.session.add(lifecycle_event)
        self.session.flush()
        self.session.refresh(lifecycle_event)
        return lifecycle_event
