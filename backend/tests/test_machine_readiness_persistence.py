"""Tests for governed persistence of pure machine-readiness results."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

import app.domain.readiness as readiness_module
import app.domain.rule_evaluation as rule_evaluation_module
from app.application.governed_unit_of_work import GovernedUnitOfWork
from app.application.machine_readiness_service import (
    MachineReadinessPersistenceDraft,
    MachineReadinessService,
)
from app.application.rule_evaluation_service import (
    RuleEvaluationPersistenceDraft,
    RuleEvaluationService,
)
from app.application.rule_registry_service import (
    GovernedAuditMetadata,
    RuleRegistryService,
)
from app.db.session import Base
from app.domain.governance_types import ContentVersionMetadata, EvidenceClass
from app.domain.idempotency_types import CanonicalRequestHash, CommandIdentity
from app.domain.readiness import (
    GovernedApplicabilityContext,
    GovernedMachineReadinessCheck,
    GovernedRuleEvaluationSnapshot,
    MachineReadinessResult,
    ReadinessState,
    evaluate_machine_readiness,
)
from app.domain.rule_applicability import (
    ApplicabilityResolutionOutcome,
    GovernedApplicabilityCandidate,
    GovernedApplicabilityResolution,
    resolve_governed_applicability,
)
from app.domain.rule_evaluation import (
    Observation,
    RuleComparison,
    RuleRequirement,
    compare_rule,
)
from app.domain.rule_registry_types import (
    MissingHandling,
    RuleCategory,
    RuleOperator,
    SafeDefault,
)
from app.domain.unit_policy import UnitPolicyContext
from app.models.governance import (
    GovernedAuditEvent,
    GovernedCommandReceipt,
    freeze_json,
)
from app.models.machine_readiness import (
    MachineReadinessAssessment,
    MachineReadinessAssessmentRevision,
    MachineReadinessCheckResult,
)
from app.models.rule_evaluation import RuleEvaluation
from app.repositories.governance_repository import GovernanceRepository

RULE_ID = "MRC_RULE_A"
RULE_REVISION = "1.0"
ASSESSMENT_ID = "assessment-mrc"
DECISION_TIME = datetime(2034, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
AUDIT_TIME = datetime(2034, 1, 2, 3, 4, 6, tzinfo=timezone.utc)
EVALUATION_UNIT = "synthetic_unit"


@pytest.fixture()
def persistence_engine():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    yield engine
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        Base.metadata.drop_all(connection)
    engine.dispose()


def _audit(event_id: str, *, reason: str = "Synthetic MRC persistence test") -> GovernedAuditMetadata:
    return GovernedAuditMetadata(
        event_id=event_id,
        actor_id="synthetic-actor",
        actor_type="service",
        actor_user_id=None,
        actor_role="synthetic-role",
        authority_scope={"project": "synthetic-project"},
        reason=reason,
        correlation_id="synthetic-correlation",
        idempotency_key="synthetic-idempotency-key",
        schema_version="audit-test-v1",
        software_version="test-build",
        canonicalization_version="audit-canonical-v1",
        hash_algorithm="sha256",
        detail={"caller": "synthetic"},
        created_at=AUDIT_TIME,
    )


def _version(label: str) -> ContentVersionMetadata:
    payload = json.dumps(
        {"rule_id": RULE_ID, "revision": label},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return ContentVersionMetadata(
        schema_version="registry-test-v1",
        canonicalization_version="registry-canonical-v1",
        hash_algorithm="sha256",
        content_hash=hashlib.sha256(payload).hexdigest(),
        software_version="test-build",
    )


def _seed_rule(session: Session, *, revision: str = RULE_REVISION) -> None:
    with GovernedUnitOfWork(session) as unit_of_work:
        service = RuleRegistryService(unit_of_work)
        service.create_identity(rule_id=RULE_ID, audit=_audit(f"{revision}-identity"))
        service.create_draft_revision(
            rule_id=RULE_ID,
            revision=revision,
            name="Synthetic persisted MRC rule",
            evidence_class=EvidenceClass.UNRESOLVED,
            category=RuleCategory.OTHER,
            parameter="synthetic_parameter",
            safe_default=SafeDefault.UNRESOLVED,
            missing_handling=MissingHandling.DATA_INSUFFICIENT,
            reason_for_change="Synthetic persisted MRC seed",
            version_metadata=_version(revision),
            audit=_audit(f"{revision}-revision"),
            enabled=False,
        )
        unit_of_work.commit()


def _mrc_context() -> GovernedApplicabilityContext:
    return GovernedApplicabilityContext(
        customer="customer-a",
        project="project-a",
        site="site-a",
        machine="machine-a",
    )


def _selected_applicability_result(
    *,
    context: GovernedApplicabilityContext | None = None,
    rule_id: str = RULE_ID,
    revision: str = RULE_REVISION,
) -> tuple[GovernedApplicabilityContext, GovernedApplicabilityResolution]:
    context = context or _mrc_context()
    candidate = GovernedApplicabilityCandidate(
        candidate_id=f"{rule_id}:{revision}",
        rule_id=rule_id,
        revision=revision,
        evidence_class=EvidenceClass.SOURCE_BACKED,
        enabled=True,
        active=True,
        scope_snapshot={
            "customer": [context.customer or ""],
            "project": [context.project or ""],
            "site": [context.site or ""],
            "machine": [context.machine or ""],
        },
        effective_from=DECISION_TIME - timedelta(days=1),
    )
    resolution = resolve_governed_applicability(context, DECISION_TIME, [candidate])
    assert resolution.outcome is ApplicabilityResolutionOutcome.SELECTED
    return context, resolution


def _requirement(
    *,
    enabled: bool = True,
    min_value: float | None = 10.0,
) -> RuleRequirement:
    return RuleRequirement(
        rule_id=RULE_ID,
        revision=RULE_REVISION,
        parameter="synthetic_parameter",
        operator=RuleOperator.MIN,
        unit=EVALUATION_UNIT,
        min_value=min_value,
        enabled=enabled,
    )


def _observation(value: float | None) -> Observation | None:
    if value is None:
        return None
    return Observation(
        parameter="synthetic_parameter",
        value=value,
        unit=EVALUATION_UNIT,
    )


def _comparison(
    *,
    value: float | None,
    enabled: bool = True,
    applicability_result: GovernedApplicabilityResolution | None = None,
    rule_id: str = RULE_ID,
    revision: str = RULE_REVISION,
) -> RuleComparison:
    applicability_result = applicability_result or _selected_applicability_result()[1]
    return compare_rule(
        RuleRequirement(
            rule_id=rule_id,
            revision=revision,
            parameter="synthetic_parameter",
            operator=RuleOperator.MIN,
            unit=EVALUATION_UNIT,
            min_value=10.0,
            enabled=enabled,
        ),
        _observation(value),
        applicability_result=applicability_result,
        unit_context=UnitPolicyContext(expected_unit=EVALUATION_UNIT),
    )


def _snapshot(
    check_id: str,
    comparison: RuleComparison,
    *,
    evaluation_id: str | None = None,
) -> GovernedRuleEvaluationSnapshot:
    return GovernedRuleEvaluationSnapshot(
        evaluation_id=evaluation_id or f"{check_id}:evaluation",
        revision_number=1,
        comparison=comparison,
    )


def _check(
    check_id: str,
    *,
    required: bool = True,
    evaluations: tuple[GovernedRuleEvaluationSnapshot, ...] = (),
    description: str | None = None,
) -> GovernedMachineReadinessCheck:
    return GovernedMachineReadinessCheck(
        check_id=check_id,
        required=required,
        evaluations=evaluations,
        description=description,
    )


def _persist_rule_evaluation(
    session: Session,
    *,
    comparison: RuleComparison,
    applicability_result: GovernedApplicabilityResolution,
    observation: Observation | None,
    evaluation_id: str,
    receipt_id: str,
    audit_event_id: str,
) -> RuleEvaluation:
    if session.in_transaction():
        session.rollback()
    with GovernedUnitOfWork(session) as unit_of_work:
        service = RuleEvaluationService(unit_of_work)
        service.persist_evaluation(
            draft=RuleEvaluationPersistenceDraft(
                evaluation_id=evaluation_id,
                revision_number=1,
                comparison=comparison,
                applicability_result=applicability_result,
                observation=observation,
                unit_context=UnitPolicyContext(expected_unit=EVALUATION_UNIT),
            ),
            receipt_id=receipt_id,
            command_identity=CommandIdentity(
                command_namespace=RuleEvaluationService.COMMAND_NAMESPACE,
                command_scope=evaluation_id,
                idempotency_key=f"{evaluation_id}-idempotency",
            ),
            request_hash=CanonicalRequestHash(
                value=hashlib.sha256(evaluation_id.encode("utf-8")).hexdigest(),
                hash_algorithm="sha256",
                canonicalization_version="rule-evaluation-persistence-canonical-v1",
            ),
            audit=_audit(audit_event_id),
            completed_at=AUDIT_TIME,
        )
        unit_of_work.commit()

    persisted = session.scalar(
        select(RuleEvaluation).where(
            RuleEvaluation.evaluation_id == evaluation_id,
            RuleEvaluation.revision_number == 1,
        )
    )
    assert persisted is not None
    session.rollback()
    return persisted


def _persist_assessment(
    session: Session,
    *,
    result: MachineReadinessResult,
    checks: tuple[GovernedMachineReadinessCheck, ...],
    assessment_id: str,
    revision_number: int,
    supersedes_assessment_revision_id: int | None = None,
    receipt_id: str | None = None,
    audit_event_id: str | None = None,
    idempotency_key: str | None = None,
    request_payload: str | None = None,
) -> tuple[MachineReadinessAssessmentRevision | None, GovernedCommandReceipt, GovernedAuditEvent]:
    draft = MachineReadinessPersistenceDraft(
        assessment_id=assessment_id,
        revision_number=revision_number,
        result=result,
        checks=checks,
        supersedes_assessment_revision_id=supersedes_assessment_revision_id,
    )
    receipt_id = receipt_id or f"{assessment_id}-receipt-{revision_number}"
    audit_event_id = audit_event_id or f"{assessment_id}-event-{revision_number}"
    idempotency_key = idempotency_key or f"{assessment_id}-key-{revision_number}"
    request_payload = request_payload or f"{assessment_id}-payload-{revision_number}"

    if session.in_transaction():
        session.rollback()
    with GovernedUnitOfWork(session) as unit_of_work:
        service = MachineReadinessService(unit_of_work)
        result_ref = service.persist_assessment(
            draft=draft,
            receipt_id=receipt_id,
            command_identity=CommandIdentity(
                command_namespace=MachineReadinessService.COMMAND_NAMESPACE,
                command_scope=assessment_id,
                idempotency_key=idempotency_key,
            ),
            request_hash=CanonicalRequestHash(
                value=hashlib.sha256(request_payload.encode("utf-8")).hexdigest(),
                hash_algorithm="sha256",
                canonicalization_version="machine-readiness-persistence-canonical-v1",
            ),
            audit=_audit(audit_event_id),
            completed_at=AUDIT_TIME,
        )
        assert result_ref.result_type in {"machine_readiness", "machine_readiness_denial"}
        unit_of_work.commit()

    revision = session.scalar(
        select(MachineReadinessAssessmentRevision).where(
            MachineReadinessAssessmentRevision.assessment_id == assessment_id,
            MachineReadinessAssessmentRevision.revision_number == revision_number,
        )
    )
    receipt = session.scalar(
        select(GovernedCommandReceipt).where(
            GovernedCommandReceipt.command_namespace
            == MachineReadinessService.COMMAND_NAMESPACE,
            GovernedCommandReceipt.command_scope == assessment_id,
            GovernedCommandReceipt.idempotency_key == idempotency_key,
        )
    )
    audit_event = GovernanceRepository(session).get_by_event_id(audit_event_id)
    assert receipt is not None
    assert audit_event is not None
    session.rollback()
    return revision, receipt, audit_event


def _ready_case(
    session: Session,
) -> tuple[MachineReadinessResult, tuple[GovernedMachineReadinessCheck, ...]]:
    _seed_rule(session)
    context, selected = _selected_applicability_result()
    satisfied = _comparison(value=11.0, applicability_result=selected)
    not_applicable = _comparison(value=11.0, enabled=False, applicability_result=selected)
    _persist_rule_evaluation(
        session,
        comparison=satisfied,
        applicability_result=selected,
        observation=_observation(11.0),
        evaluation_id="evaluation-ready-required",
        receipt_id="evaluation-ready-required-receipt",
        audit_event_id="evaluation-ready-required-event",
    )
    _persist_rule_evaluation(
        session,
        comparison=not_applicable,
        applicability_result=selected,
        observation=None,
        evaluation_id="evaluation-ready-optional",
        receipt_id="evaluation-ready-optional-receipt",
        audit_event_id="evaluation-ready-optional-event",
    )
    checks = (
        _check(
            "optional-check",
            required=False,
            evaluations=(
                _snapshot("optional-check", not_applicable, evaluation_id="evaluation-ready-optional"),
            ),
        ),
        _check(
            "required-check",
            evaluations=(
                _snapshot("required-check", satisfied, evaluation_id="evaluation-ready-required"),
            ),
        ),
    )
    result = evaluate_machine_readiness(
        context,
        DECISION_TIME,
        checks,
    )
    assert result.state is ReadinessState.READY
    return result, checks


def _not_ready_case(
    session: Session,
) -> tuple[MachineReadinessResult, tuple[GovernedMachineReadinessCheck, ...]]:
    _seed_rule(session)
    context, selected = _selected_applicability_result()
    not_satisfied = _comparison(value=5.0, applicability_result=selected)
    _persist_rule_evaluation(
        session,
        comparison=not_satisfied,
        applicability_result=selected,
        observation=_observation(5.0),
        evaluation_id="evaluation-not-ready",
        receipt_id="evaluation-not-ready-receipt",
        audit_event_id="evaluation-not-ready-event",
    )
    checks = (
        _check(
            "required-check",
            evaluations=(
                _snapshot("required-check", not_satisfied, evaluation_id="evaluation-not-ready"),
            ),
        ),
    )
    result = evaluate_machine_readiness(context, DECISION_TIME, checks)
    assert result.state is ReadinessState.NOT_READY
    return result, checks


def _engineering_review_case(
    session: Session,
) -> tuple[MachineReadinessResult, tuple[GovernedMachineReadinessCheck, ...]]:
    _seed_rule(session)
    context, selected = _selected_applicability_result()
    unresolved = _comparison(value=None, applicability_result=selected)
    _persist_rule_evaluation(
        session,
        comparison=unresolved,
        applicability_result=selected,
        observation=None,
        evaluation_id="evaluation-engineering",
        receipt_id="evaluation-engineering-receipt",
        audit_event_id="evaluation-engineering-event",
    )
    checks = (
        _check(
            "required-check",
            evaluations=(
                _snapshot(
                    "required-check",
                    unresolved,
                    evaluation_id="evaluation-engineering",
                ),
            ),
        ),
    )
    result = evaluate_machine_readiness(context, DECISION_TIME, checks)
    assert result.state is ReadinessState.ENGINEERING_REVIEW_REQUIRED
    return result, checks


def _manual_review_case(
    session: Session,
) -> tuple[MachineReadinessResult, tuple[GovernedMachineReadinessCheck, ...]]:
    _seed_rule(session)
    context, selected = _selected_applicability_result()
    satisfied = _comparison(value=11.0, applicability_result=selected)
    _persist_rule_evaluation(
        session,
        comparison=satisfied,
        applicability_result=selected,
        observation=_observation(11.0),
        evaluation_id="evaluation-manual-optional",
        receipt_id="evaluation-manual-optional-receipt",
        audit_event_id="evaluation-manual-optional-event",
    )
    checks = (
        _check("required-missing", evaluations=()),
        _check(
            "optional-satisfied",
            required=False,
            evaluations=(
                _snapshot(
                    "optional-satisfied",
                    satisfied,
                    evaluation_id="evaluation-manual-optional",
                ),
            ),
        ),
    )
    result = evaluate_machine_readiness(context, DECISION_TIME, checks)
    assert result.state is ReadinessState.MANUAL_REVIEW_REQUIRED
    return result, checks


def _not_evaluated_case(
    session: Session | None = None,
) -> tuple[MachineReadinessResult, tuple[GovernedMachineReadinessCheck, ...]]:
    context = _mrc_context()
    checks: tuple[GovernedMachineReadinessCheck, ...] = ()
    result = evaluate_machine_readiness(context, DECISION_TIME, checks)
    assert result.state is ReadinessState.NOT_EVALUATED
    return result, checks


@pytest.mark.parametrize(
    "builder, expected_state",
    [
        (_ready_case, ReadinessState.READY),
        (_not_ready_case, ReadinessState.NOT_READY),
        (_engineering_review_case, ReadinessState.ENGINEERING_REVIEW_REQUIRED),
        (_manual_review_case, ReadinessState.MANUAL_REVIEW_REQUIRED),
        (_not_evaluated_case, ReadinessState.NOT_EVALUATED),
    ],
)
def test_persists_all_pure_outcomes_and_preserves_provenance(
    persistence_engine,
    builder,
    expected_state,
):
    with Session(persistence_engine) as session:
        result, checks = builder(session)
        revision, receipt, audit_event = _persist_assessment(
            session,
            result=result,
            checks=checks,
            assessment_id=f"{ASSESSMENT_ID}-{expected_state.value.lower()}",
            revision_number=1,
            receipt_id=f"{ASSESSMENT_ID}-{expected_state.value.lower()}-receipt",
            audit_event_id=f"{ASSESSMENT_ID}-{expected_state.value.lower()}-event",
            idempotency_key=f"{ASSESSMENT_ID}-{expected_state.value.lower()}-key",
            request_payload=f"{ASSESSMENT_ID}-{expected_state.value.lower()}-payload",
        )

        assert revision is not None
        assert revision.state is expected_state
        assert revision.revision_number == 1
        assert revision.context_snapshot == freeze_json(result.context.as_mapping())
        assert revision.decision_time.replace(tzinfo=None) == DECISION_TIME.replace(
            tzinfo=None
        )
        assert revision.validated_applicable_basis_count == result.validated_applicable_basis_count
        assert revision.result_snapshot["state"] == expected_state.value
        assert audit_event.action in {
            "PERSIST_MACHINE_READINESS_ASSESSMENT",
            "CORRECT_MACHINE_READINESS_ASSESSMENT",
        }
        assert receipt.status.value == "COMPLETED"
        assert receipt.result_type == "machine_readiness"
        assert receipt.result_revision == "1"

        persisted_checks = session.scalars(
            select(MachineReadinessCheckResult).where(
                MachineReadinessCheckResult.assessment_revision_id == revision.id
            )
        ).all()
        assert len(persisted_checks) == len(checks)
        if persisted_checks:
            assert persisted_checks == sorted(persisted_checks, key=lambda item: item.id)
            assert persisted_checks[0].check_snapshot["check_id"] in {
                "optional-satisfied",
                "optional-check",
                "required-check",
                "required-missing",
            }


def test_exact_pins_and_no_recomputation(persistence_engine, monkeypatch):
    with Session(persistence_engine) as session:
        result, checks = _ready_case(session)

        monkeypatch.setattr(
            readiness_module,
            "evaluate_machine_readiness",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("pure readiness evaluator must not run during persistence")
            ),
        )
        monkeypatch.setattr(
            rule_evaluation_module,
            "compare_rule",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("comparison must not run during persistence")
            ),
        )

        revision, _, _ = _persist_assessment(
            session,
            result=result,
            checks=checks,
            assessment_id="assessment-pins",
            revision_number=1,
            receipt_id="assessment-pins-receipt",
            audit_event_id="assessment-pins-event",
            idempotency_key="assessment-pins-key",
            request_payload="assessment-pins-payload",
        )

        assert revision is not None
        assert revision.context_snapshot == freeze_json(result.context.as_mapping())
        assert revision.result_snapshot["checks"][0]["evaluations"][0]["evaluation_id"] == "evaluation-ready-optional"
        assert revision.result_snapshot["checks"][1]["evaluations"][0]["evaluation_id"] == "evaluation-ready-required"
        assert revision.authority_snapshot["policy_identifier"] == MachineReadinessService.COMMAND_NAMESPACE


def test_correction_is_append_only_and_branching_is_rejected(persistence_engine):
    with Session(persistence_engine) as session:
        first_result, first_checks = _ready_case(session)
        first_revision, _, _ = _persist_assessment(
            session,
            result=first_result,
            checks=first_checks,
            assessment_id="assessment-correction",
            revision_number=1,
            receipt_id="assessment-correction-receipt-1",
            audit_event_id="assessment-correction-event-1",
            idempotency_key="assessment-correction-key-1",
            request_payload="assessment-correction-payload-1",
        )
        assert first_revision is not None

        with GovernedUnitOfWork(session) as unit_of_work:
            service = RuleRegistryService(unit_of_work)
            service.create_draft_revision(
                rule_id=RULE_ID,
                revision="2.0",
                name="Synthetic persisted MRC rule",
                evidence_class=EvidenceClass.UNRESOLVED,
                category=RuleCategory.OTHER,
                parameter="synthetic_parameter",
                safe_default=SafeDefault.UNRESOLVED,
                missing_handling=MissingHandling.DATA_INSUFFICIENT,
                reason_for_change="Synthetic persisted MRC seed",
                version_metadata=_version("2.0"),
                audit=_audit("2.0-revision"),
                enabled=False,
            )
            unit_of_work.commit()
        context, selected = _selected_applicability_result(revision="2.0")
        not_satisfied = _comparison(value=5.0, revision="2.0", applicability_result=selected)
        _persist_rule_evaluation(
            session,
            comparison=not_satisfied,
            applicability_result=selected,
            observation=_observation(5.0),
            evaluation_id="evaluation-correction",
            receipt_id="evaluation-correction-receipt",
            audit_event_id="evaluation-correction-event",
        )
        second_result = evaluate_machine_readiness(
            context,
            DECISION_TIME,
            (
                _check(
                    "required-check",
                    evaluations=(
                        _snapshot(
                            "required-check",
                            not_satisfied,
                            evaluation_id="evaluation-correction",
                        ),
                    ),
                ),
            ),
        )
        second_revision, _, second_audit = _persist_assessment(
            session,
            result=second_result,
            checks=(
                _check(
                    "required-check",
                    evaluations=(
                        _snapshot(
                            "required-check",
                            not_satisfied,
                            evaluation_id="evaluation-correction",
                        ),
                    ),
                ),
            ),
            assessment_id="assessment-correction",
            revision_number=2,
            supersedes_assessment_revision_id=first_revision.id,
            receipt_id="assessment-correction-receipt-2",
            audit_event_id="assessment-correction-event-2",
            idempotency_key="assessment-correction-key-2",
            request_payload="assessment-correction-payload-2",
        )
        assert second_revision is not None
        assert second_revision.revision_number == 2
        assert second_revision.supersedes_assessment_revision_id == first_revision.id
        assert second_audit.action == "CORRECT_MACHINE_READINESS_ASSESSMENT"
        assert session.scalar(
            select(MachineReadinessAssessmentRevision).where(
                MachineReadinessAssessmentRevision.assessment_id == "assessment-correction",
                MachineReadinessAssessmentRevision.revision_number == 1,
            )
        ).state is ReadinessState.READY

        session.rollback()
        with GovernedUnitOfWork(session) as unit_of_work:
            service = MachineReadinessService(unit_of_work)
            denial = service.persist_assessment(
                draft=MachineReadinessPersistenceDraft(
                    assessment_id="assessment-correction",
                    revision_number=3,
                    result=second_result,
                    checks=(
                        _check(
                            "required-check",
                            evaluations=(
                                _snapshot(
                                    "required-check",
                                    not_satisfied,
                                    evaluation_id="evaluation-correction",
                                ),
                            ),
                        ),
                    ),
                    supersedes_assessment_revision_id=first_revision.id,
                ),
                receipt_id="assessment-correction-receipt-3",
                command_identity=CommandIdentity(
                    command_namespace=MachineReadinessService.COMMAND_NAMESPACE,
                    command_scope="assessment-correction",
                    idempotency_key="assessment-correction-key-3",
                ),
                request_hash=CanonicalRequestHash(
                    value=hashlib.sha256(b"assessment-correction-payload-3").hexdigest(),
                    hash_algorithm="sha256",
                    canonicalization_version="machine-readiness-persistence-canonical-v1",
                ),
                audit=_audit("assessment-correction-event-3"),
                completed_at=AUDIT_TIME,
            )
            assert denial.result_type == "machine_readiness_denial"
            unit_of_work.commit()
        denial_audit = GovernanceRepository(session).get_by_event_id(
            "assessment-correction-event-3"
        )
        assert denial_audit is not None
        assert denial_audit.action == "PERSIST_MACHINE_READINESS_ASSESSMENT_DENIED"


def test_idempotency_audit_and_atomic_rollback(persistence_engine, monkeypatch):
    with Session(persistence_engine) as session:
        result, checks = _ready_case(session)
        first_revision, first_receipt, first_audit = _persist_assessment(
            session,
            result=result,
            checks=checks,
            assessment_id="assessment-idempotent",
            revision_number=1,
            receipt_id="assessment-idempotent-receipt-1",
            audit_event_id="assessment-idempotent-event-1",
            idempotency_key="assessment-idempotent-key",
            request_payload="same-request",
        )
        assert first_revision is not None
        assert first_audit.action == "PERSIST_MACHINE_READINESS_ASSESSMENT"
        assert first_receipt.status.value == "COMPLETED"

        session.rollback()
        with GovernedUnitOfWork(session) as unit_of_work:
            service = MachineReadinessService(unit_of_work)
            replay = service.persist_assessment(
                draft=MachineReadinessPersistenceDraft(
                    assessment_id="assessment-idempotent",
                    revision_number=1,
                    result=result,
                    checks=checks,
                ),
                receipt_id="unused-replay-receipt",
                command_identity=CommandIdentity(
                    command_namespace=MachineReadinessService.COMMAND_NAMESPACE,
                    command_scope="assessment-idempotent",
                    idempotency_key="assessment-idempotent-key",
                ),
                request_hash=CanonicalRequestHash(
                    value=hashlib.sha256(b"same-request").hexdigest(),
                    hash_algorithm="sha256",
                    canonicalization_version="machine-readiness-persistence-canonical-v1",
                ),
                audit=_audit("assessment-idempotent-event-replay"),
                completed_at=AUDIT_TIME,
            )
            assert replay.result_type == "machine_readiness"
            unit_of_work.commit()

        session.rollback()
        with Session(persistence_engine) as conflict_session, pytest.raises(
            ValueError, match="idempotency conflict"
        ), GovernedUnitOfWork(conflict_session) as unit_of_work:
            service = MachineReadinessService(unit_of_work)
            service.persist_assessment(
                draft=MachineReadinessPersistenceDraft(
                    assessment_id="assessment-idempotent",
                    revision_number=1,
                    result=result,
                    checks=checks,
                ),
                receipt_id="unused-conflict-receipt",
                command_identity=CommandIdentity(
                    command_namespace=MachineReadinessService.COMMAND_NAMESPACE,
                    command_scope="assessment-idempotent",
                    idempotency_key="assessment-idempotent-key",
                ),
                request_hash=CanonicalRequestHash(
                    value=hashlib.sha256(b"different-request").hexdigest(),
                    hash_algorithm="sha256",
                    canonicalization_version="machine-readiness-persistence-canonical-v1",
                ),
                audit=_audit("assessment-idempotent-event-conflict"),
                completed_at=AUDIT_TIME,
            )

        session.rollback()
        with Session(persistence_engine) as reserved_session, GovernedUnitOfWork(
            reserved_session
        ) as unit_of_work:
            service = MachineReadinessService(unit_of_work)
            service._idempotency.reserve_or_inspect(
                receipt_id="assessment-in-progress-receipt",
                identity=CommandIdentity(
                    command_namespace=MachineReadinessService.COMMAND_NAMESPACE,
                    command_scope="assessment-in-progress",
                    idempotency_key="assessment-in-progress-key",
                ),
                request_hash=CanonicalRequestHash(
                    value=hashlib.sha256(b"pending-request").hexdigest(),
                    hash_algorithm="sha256",
                    canonicalization_version="machine-readiness-persistence-canonical-v1",
                ),
                correlation_id="synthetic-correlation",
                schema_version="audit-test-v1",
                software_version="test-build",
                created_at=AUDIT_TIME,
                )
            unit_of_work.commit()

        session.rollback()
        with Session(persistence_engine) as in_progress_session, pytest.raises(
            RuntimeError, match="already in progress"
        ), GovernedUnitOfWork(in_progress_session) as unit_of_work:
            service = MachineReadinessService(unit_of_work)
            service.persist_assessment(
                draft=MachineReadinessPersistenceDraft(
                    assessment_id="assessment-in-progress",
                    revision_number=1,
                    result=result,
                    checks=checks,
                ),
                receipt_id="unused-in-progress-receipt",
                command_identity=CommandIdentity(
                    command_namespace=MachineReadinessService.COMMAND_NAMESPACE,
                    command_scope="assessment-in-progress",
                    idempotency_key="assessment-in-progress-key",
                ),
                request_hash=CanonicalRequestHash(
                    value=hashlib.sha256(b"pending-request").hexdigest(),
                    hash_algorithm="sha256",
                    canonicalization_version="machine-readiness-persistence-canonical-v1",
                ),
                audit=_audit("assessment-in-progress-event"),
                completed_at=AUDIT_TIME,
            )

        session.rollback()
        with GovernedUnitOfWork(session) as unit_of_work:
            service = MachineReadinessService(unit_of_work)
            monkeypatch.setattr(
                service._audit,
                "record_event",
                lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    RuntimeError("audit failure")
                ),
            )
            with pytest.raises(RuntimeError, match="audit failure"):
                service.persist_assessment(
                    draft=MachineReadinessPersistenceDraft(
                        assessment_id="assessment-rollback",
                        revision_number=1,
                        result=result,
                        checks=checks,
                    ),
                    receipt_id="assessment-rollback-receipt",
                    command_identity=CommandIdentity(
                        command_namespace=MachineReadinessService.COMMAND_NAMESPACE,
                        command_scope="assessment-rollback",
                        idempotency_key="assessment-rollback-key",
                    ),
                    request_hash=CanonicalRequestHash(
                        value=hashlib.sha256(b"assessment-rollback").hexdigest(),
                        hash_algorithm="sha256",
                        canonicalization_version="machine-readiness-persistence-canonical-v1",
                    ),
                    audit=_audit("assessment-rollback-event"),
                    completed_at=AUDIT_TIME,
                )

        assert (
            session.scalar(
                select(MachineReadinessAssessment).where(
                    MachineReadinessAssessment.assessment_id == "assessment-rollback"
                )
            )
            is None
        )
        assert (
            session.scalar(
                select(MachineReadinessAssessmentRevision).where(
                    MachineReadinessAssessmentRevision.assessment_id
                    == "assessment-rollback"
                )
            )
            is None
        )
        assert (
            GovernanceRepository(session).get_by_event_id("assessment-rollback-event")
            is None
        )
