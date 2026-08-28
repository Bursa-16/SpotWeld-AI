from __future__ import annotations

import inspect
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

service_module = pytest.importorskip("app.application.digital_weld_passport_service")
pytest.importorskip("app.application.governed_unit_of_work")
pytest.importorskip("app.application.rule_registry_service")
pytest.importorskip("app.domain.idempotency_types")
pytest.importorskip("app.domain.readiness")
pytest.importorskip("app.db.session")
pytest.importorskip("app.models.digital_weld_passport")
pytest.importorskip("app.models.machine_readiness")
pytest.importorskip("app.models.entities")

import app.models  # noqa: F401
from app.application.governed_unit_of_work import GovernedUnitOfWork
from app.application.rule_registry_service import GovernedAuditMetadata
from app.db.session import Base
from app.domain.idempotency_types import CanonicalRequestHash, CommandIdentity
from app.domain.readiness import ReadinessState
from app.models.digital_weld_passport import (
    DigitalWeldPassport,
    DigitalWeldPassportLifecycleState,
    DigitalWeldPassportRevision,
)
from app.models.entities import User
from app.models.machine_readiness import (
    MachineReadinessAssessment,
    MachineReadinessAssessmentRevision,
)

DigitalWeldPassportLifecycleTransitionDraft = (
    service_module.DigitalWeldPassportLifecycleTransitionDraft
)
DigitalWeldPassportRevisionDraft = service_module.DigitalWeldPassportRevisionDraft
DigitalWeldPassportService = service_module.DigitalWeldPassportService


@pytest.fixture()
def engine():
    database_engine = create_engine("sqlite:///:memory:")

    @event.listens_for(database_engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(database_engine)
    yield database_engine
    with database_engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        Base.metadata.drop_all(connection)
    database_engine.dispose()


def _audit(
    event_id: str,
    *,
    actor_user_id: int,
    authority_scope: dict[str, object],
    reason: str = "Synthetic DWP test",
    actor_id: str = "synthetic-actor",
    actor_type: str = "user",
    actor_role: str = "passport-authorizer",
) -> GovernedAuditMetadata:
    return GovernedAuditMetadata(
        event_id=event_id,
        actor_id=actor_id,
        actor_type=actor_type,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        authority_scope=authority_scope,
        reason=reason,
        correlation_id=f"{event_id}-correlation",
        idempotency_key=f"{event_id}-idempotency",
        schema_version="dwp-test-v1",
        software_version="test-build",
        canonicalization_version="dwp-canonical-v1",
        hash_algorithm="sha256",
        detail={"test": "dwp"},
        created_at=datetime(2036, 1, 2, 3, 4, 5, tzinfo=timezone.utc),
    )


def _command_identity(namespace: str, scope: str, name: str) -> CommandIdentity:
    signature = inspect.signature(CommandIdentity)
    kwargs: dict[str, object] = {}
    for parameter in signature.parameters.values():
        if parameter.name == "command_namespace":
            kwargs[parameter.name] = namespace
        elif parameter.name == "command_scope":
            kwargs[parameter.name] = scope
        elif parameter.name == "command_name":
            kwargs[parameter.name] = name
        elif parameter.name == "command_version":
            kwargs[parameter.name] = "1"
        elif parameter.name == "command_action":
            kwargs[parameter.name] = name
        elif parameter.default is inspect.Signature.empty:
            kwargs[parameter.name] = f"{parameter.name}-{name}"
    return CommandIdentity(**kwargs)  # type: ignore[arg-type]


def _request_hash(label: str) -> CanonicalRequestHash:
    signature = inspect.signature(CanonicalRequestHash)
    kwargs: dict[str, object] = {}
    for parameter in signature.parameters.values():
        if parameter.name in {"value", "hash_value", "digest", "canonical_hash"}:
            kwargs[parameter.name] = label
        elif parameter.name == "hash_algorithm":
            kwargs[parameter.name] = "sha256"
        elif parameter.name == "canonicalization_version":
            kwargs[parameter.name] = "dwp-canonical-v1"
        elif parameter.default is inspect.Signature.empty:
            kwargs[parameter.name] = f"{parameter.name}-{label}"
    return CanonicalRequestHash(**kwargs)  # type: ignore[arg-type]


def _create_user(session: Session, user_id: int) -> User:
    columns = User.__table__.columns
    values: dict[str, object] = {}
    for column in columns:
        if column.name == "id":
            values[column.name] = user_id
            continue
        if column.nullable:
            continue
        if column.default is not None or column.server_default is not None:
            continue
        if column.name in {"is_active", "active", "enabled"}:
            values[column.name] = True
        elif column.name in {"email", "username", "name", "full_name"}:
            values[column.name] = f"{column.name}-{user_id}"
        elif column.name.endswith("_id"):
            values[column.name] = user_id
        elif column.name.startswith("created_") or column.name.endswith("_at"):
            values[column.name] = datetime(2036, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
        else:
            values[column.name] = f"{column.name}-{user_id}"
    user = User(**values)  # type: ignore[arg-type]
    session.add(user)
    session.flush()
    return user


def _create_ready_mrc(
    session: Session,
    assessment_id: str,
    revision_number: int = 1,
    *,
    passport_id: str = "passport-1",
    scope_snapshot: dict[str, object] | None = None,
) -> MachineReadinessAssessmentRevision:
    resolved_scope_snapshot = scope_snapshot or {"project": "P1"}
    assessment = MachineReadinessAssessment(
        assessment_id=assessment_id,
        created_by_user_id=None,
        created_by_actor_id="synthetic-mrc-actor",
    )
    session.add(assessment)
    session.flush()
    revision = MachineReadinessAssessmentRevision(
        assessment_id=assessment.assessment_id,
        revision_number=revision_number,
        decision_time=datetime(2036, 1, 2, 3, 4, 6, tzinfo=timezone.utc).replace(tzinfo=None),
        state=ReadinessState.READY,
        context_snapshot={"passport_id": passport_id, "scope_snapshot": resolved_scope_snapshot},
        prerequisites_snapshot={"validated_applicable_basis_count": 1},
        result_snapshot={"state": ReadinessState.READY.value},
        authority_snapshot={"scope_snapshot": resolved_scope_snapshot},
        validated_applicable_basis_count=1,
        created_by_user_id=None,
        created_by_actor_id="synthetic-mrc-actor",
        schema_version="mrc-test-v1",
        canonicalization_version="mrc-canonical-v1",
        hash_algorithm="sha256",
        content_hash=f"{assessment_id}:{revision_number}",
        software_version="test-build",
        correlation_id=f"{assessment_id}-correlation",
        supersedes_assessment_revision_id=None,
    )
    session.add(revision)
    session.flush()
    return revision


def _passport_context(
    passport_id: str = "passport-1",
    scope_snapshot: dict[str, object] | None = None,
) -> dict[str, object]:
    resolved_scope_snapshot = scope_snapshot or {"project": "P1"}
    return {
        "passport_id": passport_id,
        "weld_identity": {"project": "P1", "site": "S1", "machine": "M1"},
        "scope_snapshot": resolved_scope_snapshot,
    }


def _passport_provenance() -> dict[str, object]:
    return {"rule_evaluations": []}


def _passport_authority(scope_snapshot: dict[str, object]) -> dict[str, object]:
    return {"scope_snapshot": scope_snapshot}


def test_draft_creation_transition_and_correction_are_append_only(engine):
    session = Session(engine)
    try:
        creator = _create_user(session, 1)
        validator = _create_user(session, 2)
        approver = _create_user(session, 3)
        _create_ready_mrc(session, "assessment-passport-1")
        session.commit()

        with GovernedUnitOfWork(session) as uow:
            service = DigitalWeldPassportService(uow)
            scope = {"project": "P1"}
            draft = DigitalWeldPassportRevisionDraft(
                passport_id="passport-1",
                revision_number=1,
                context_snapshot=_passport_context(),
                provenance_snapshot=_passport_provenance(),
                authority_snapshot=_passport_authority(scope),
                mrc_snapshot={
                    "assessment_id": "assessment-passport-1",
                    "revision_number": 1,
                    "decision_time": datetime(2036, 1, 2, 3, 4, 6, tzinfo=timezone.utc).replace(tzinfo=None).isoformat(),
                    "state": ReadinessState.READY.value,
                    "context_snapshot": {
                        "passport_id": "passport-1",
                        "scope_snapshot": scope,
                    },
                    "prerequisites_snapshot": {"validated_applicable_basis_count": 1},
                    "result_snapshot": {"state": ReadinessState.READY.value},
                    "authority_snapshot": {"scope_snapshot": scope},
                    "validated_applicable_basis_count": 1,
                    "supersedes_assessment_revision_id": None,
                    "created_by_user_id": None,
                    "created_by_actor_id": "synthetic-mrc-actor",
                    "schema_version": "mrc-test-v1",
                    "canonicalization_version": "mrc-canonical-v1",
                    "hash_algorithm": "sha256",
                    "content_hash": "assessment-passport-1:1",
                    "software_version": "test-build",
                    "correlation_id": "assessment-passport-1-correlation",
                },
            )
            create_result = service.create_draft_revision(
                draft=draft,
                receipt_id="receipt-create",
                command_identity=_command_identity("dwp.passport", "passport-1", "create"),
                request_hash=_request_hash("create-passport-1"),
                audit=_audit("dwp-create", actor_user_id=creator.id, authority_scope=scope),
                completed_at=datetime(2036, 1, 2, 3, 4, 7, tzinfo=timezone.utc),
            )
            assert create_result.result_id == "passport-1"
            assert create_result.result_revision == "1"

            revision = session.scalar(
                select(DigitalWeldPassportRevision).where(
                    DigitalWeldPassportRevision.passport_id == "passport-1",
                    DigitalWeldPassportRevision.revision_number == 1,
                )
            )
            assert revision is not None
            assert revision.content_hash
            passport = session.scalar(
                select(DigitalWeldPassport).where(
                    DigitalWeldPassport.passport_id == "passport-1"
                )
            )
            assert passport is not None
            assert passport.current_revision_id == revision.id
            assert [event.state for event in revision.lifecycle_events] == [
                DigitalWeldPassportLifecycleState.DRAFT
            ]

            validated_result = service.transition_revision(
                transition=DigitalWeldPassportLifecycleTransitionDraft(
                    passport_id="passport-1",
                    revision_number=1,
                    state=DigitalWeldPassportLifecycleState.VALIDATED,
                    reason="Validation confirmed",
                    mrc_snapshot=draft.mrc_snapshot,
                    supersedes_lifecycle_event_id=revision.lifecycle_events[-1].id,
                ),
                receipt_id="receipt-validate",
                command_identity=_command_identity("dwp.passport", "passport-1", "validate"),
                request_hash=_request_hash("validate-passport-1"),
                audit=_audit("dwp-validate", actor_user_id=validator.id, authority_scope=scope),
                completed_at=datetime(2036, 1, 2, 3, 4, 8, tzinfo=timezone.utc),
            )
            assert validated_result.result_revision == "1"

            session.expire(revision, ["lifecycle_events"])
            lifecycle_states = [event.state for event in revision.lifecycle_events]
            assert lifecycle_states == [
                DigitalWeldPassportLifecycleState.DRAFT,
                DigitalWeldPassportLifecycleState.VALIDATED,
            ]

            approved_result = service.transition_revision(
                transition=DigitalWeldPassportLifecycleTransitionDraft(
                    passport_id="passport-1",
                    revision_number=1,
                    state=DigitalWeldPassportLifecycleState.APPROVED,
                    reason="Approved after validation",
                    mrc_snapshot=draft.mrc_snapshot,
                    supersedes_lifecycle_event_id=revision.lifecycle_events[-1].id,
                ),
                receipt_id="receipt-approve",
                command_identity=_command_identity("dwp.passport", "passport-1", "approve"),
                request_hash=_request_hash("approve-passport-1"),
                audit=_audit("dwp-approve", actor_user_id=approver.id, authority_scope=scope),
                completed_at=datetime(2036, 1, 2, 3, 4, 9, tzinfo=timezone.utc),
            )
            assert approved_result.result_revision == "1"

            session.expire(revision, ["lifecycle_events"])
            correction = service.create_draft_revision(
                draft=DigitalWeldPassportRevisionDraft(
                    passport_id="passport-1",
                    revision_number=2,
                    context_snapshot=_passport_context(),
                    provenance_snapshot=_passport_provenance(),
                    authority_snapshot=_passport_authority(scope),
                    mrc_snapshot=draft.mrc_snapshot,
                    supersedes_revision_id=revision.id,
                ),
                receipt_id="receipt-correction",
                command_identity=_command_identity("dwp.passport", "passport-1", "revise"),
                request_hash=_request_hash("revise-passport-1"),
                audit=_audit("dwp-revise", actor_user_id=creator.id, authority_scope=scope),
                completed_at=datetime(2036, 1, 2, 3, 4, 10, tzinfo=timezone.utc),
            )
            assert correction.result_revision == "2"

            revision_two = session.scalar(
                select(DigitalWeldPassportRevision).where(
                    DigitalWeldPassportRevision.passport_id == "passport-1",
                    DigitalWeldPassportRevision.revision_number == 2,
                )
            )
            assert revision_two is not None
            assert revision_two.supersedes_revision_id == revision.id
            passport = session.scalar(
                select(DigitalWeldPassport).where(
                    DigitalWeldPassport.passport_id == "passport-1"
                )
            )
            assert passport is not None
            assert passport.current_revision_id == revision_two.id
    finally:
        session.close()


def test_draft_creation_is_idempotent_and_replays(engine):
    session = Session(engine)
    try:
        creator = _create_user(session, 11)
        _create_ready_mrc(session, "assessment-passport-2")
        session.commit()

        scope = {"project": "P2"}
        draft = DigitalWeldPassportRevisionDraft(
            passport_id="passport-2",
            revision_number=1,
            context_snapshot=_passport_context("passport-2"),
            provenance_snapshot=_passport_provenance(),
            authority_snapshot=_passport_authority(scope),
            mrc_snapshot={
                "assessment_id": "assessment-passport-2",
                "revision_number": 1,
                "decision_time": datetime(2036, 1, 2, 3, 4, 6, tzinfo=timezone.utc).replace(tzinfo=None).isoformat(),
                "state": ReadinessState.READY.value,
                "context_snapshot": {
                    "passport_id": "passport-2",
                    "scope_snapshot": scope,
                },
                "prerequisites_snapshot": {"validated_applicable_basis_count": 1},
                "result_snapshot": {"state": ReadinessState.READY.value},
                "authority_snapshot": {"scope_snapshot": scope},
                "validated_applicable_basis_count": 1,
                "supersedes_assessment_revision_id": None,
                "created_by_user_id": None,
                "created_by_actor_id": "synthetic-mrc-actor",
                "schema_version": "mrc-test-v1",
                "canonicalization_version": "mrc-canonical-v1",
                "hash_algorithm": "sha256",
                "content_hash": "assessment-passport-2:1",
                "software_version": "test-build",
                "correlation_id": "assessment-passport-2-correlation",
            },
        )

        with GovernedUnitOfWork(session) as uow:
            service = DigitalWeldPassportService(uow)
            command_identity = _command_identity("dwp.passport", "passport-2", "create")
            request_hash = _request_hash("create-passport-2")
            first = service.create_draft_revision(
                draft=draft,
                receipt_id="receipt-passport-2",
                command_identity=command_identity,
                request_hash=request_hash,
                audit=_audit("dwp-create-2", actor_user_id=creator.id, authority_scope=scope),
                completed_at=datetime(2036, 1, 2, 3, 4, 7, tzinfo=timezone.utc),
            )
            replay = service.create_draft_revision(
                draft=draft,
                receipt_id="receipt-passport-2",
                command_identity=command_identity,
                request_hash=request_hash,
                audit=_audit("dwp-create-2-replay", actor_user_id=creator.id, authority_scope=scope),
                completed_at=datetime(2036, 1, 2, 3, 4, 7, tzinfo=timezone.utc),
            )
            assert first == replay
    finally:
        session.close()


def test_direct_finalization_from_draft_is_denied(engine):
    session = Session(engine)
    try:
        creator = _create_user(session, 21)
        approver = _create_user(session, 22)
        _create_ready_mrc(
            session,
            "assessment-passport-3",
            passport_id="passport-3",
            scope_snapshot={"project": "P3"},
        )
        session.commit()

        scope = {"project": "P3"}
        draft = DigitalWeldPassportRevisionDraft(
            passport_id="passport-3",
            revision_number=1,
            context_snapshot=_passport_context("passport-3", {"project": "P3"}),
            provenance_snapshot=_passport_provenance(),
            authority_snapshot=_passport_authority(scope),
            mrc_snapshot={
                "assessment_id": "assessment-passport-3",
                "revision_number": 1,
                "decision_time": datetime(2036, 1, 2, 3, 4, 6, tzinfo=timezone.utc).replace(tzinfo=None).isoformat(),
                "state": ReadinessState.READY.value,
                "context_snapshot": {
                    "passport_id": "passport-3",
                    "scope_snapshot": scope,
                },
                "prerequisites_snapshot": {"validated_applicable_basis_count": 1},
                "result_snapshot": {"state": ReadinessState.READY.value},
                "authority_snapshot": {"scope_snapshot": scope},
                "validated_applicable_basis_count": 1,
                "supersedes_assessment_revision_id": None,
                "created_by_user_id": None,
                "created_by_actor_id": "synthetic-mrc-actor",
                "schema_version": "mrc-test-v1",
                "canonicalization_version": "mrc-canonical-v1",
                "hash_algorithm": "sha256",
                "content_hash": "assessment-passport-3:1",
                "software_version": "test-build",
                "correlation_id": "assessment-passport-3-correlation",
            },
        )

        with GovernedUnitOfWork(session) as uow:
            service = DigitalWeldPassportService(uow)
            service.create_draft_revision(
                draft=draft,
                receipt_id="receipt-passport-3",
                command_identity=_command_identity("dwp.passport", "passport-3", "create"),
                request_hash=_request_hash("create-passport-3"),
                audit=_audit("dwp-create-3", actor_user_id=creator.id, authority_scope=scope),
                completed_at=datetime(2036, 1, 2, 3, 4, 7, tzinfo=timezone.utc),
            )
            revision = session.scalar(
                select(DigitalWeldPassportRevision).where(
                    DigitalWeldPassportRevision.passport_id == "passport-3",
                    DigitalWeldPassportRevision.revision_number == 1,
                )
            )
            assert revision is not None
            denial = service.transition_revision(
                transition=DigitalWeldPassportLifecycleTransitionDraft(
                    passport_id="passport-3",
                    revision_number=1,
                    state=DigitalWeldPassportLifecycleState.APPROVED,
                    reason="Should be blocked",
                    mrc_snapshot=draft.mrc_snapshot,
                    supersedes_lifecycle_event_id=revision.lifecycle_events[-1].id,
                ),
                receipt_id="receipt-passport-3-approve",
                command_identity=_command_identity("dwp.passport", "passport-3", "approve"),
                request_hash=_request_hash("approve-passport-3"),
                audit=_audit("dwp-approve-3", actor_user_id=approver.id, authority_scope=scope),
                completed_at=datetime(2036, 1, 2, 3, 4, 8, tzinfo=timezone.utc),
            )
            assert denial.result_revision == "denied"
    finally:
        session.close()
