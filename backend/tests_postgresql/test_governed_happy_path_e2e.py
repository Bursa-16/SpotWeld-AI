"""Real-PostgreSQL governed engineering happy-path integration test."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

import app.domain.readiness as readiness_domain
import app.domain.rule_evaluation as rule_evaluation_domain
from app.api.v1 import digital_weld_passport as dwp_api
from app.api.v1 import machine_readiness as mrc_api
from app.application.digital_weld_passport_service import (
    DigitalWeldPassportLifecycleTransitionDraft,
    DigitalWeldPassportRevisionDraft,
    DigitalWeldPassportService,
)
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
from app.domain.governance_types import (
    ContentVersionMetadata,
    EvidenceClass,
    RuleLifecycleStatus,
)
from app.domain.idempotency_types import CanonicalRequestHash, CommandIdentity
from app.domain.readiness import (
    GovernedMachineReadinessCheck,
    GovernedRuleEvaluationSnapshot,
    ReadinessState,
    evaluate_machine_readiness,
)
from app.domain.rule_applicability import (
    ApplicabilityResolutionOutcome,
    GovernedApplicabilityCandidate,
    GovernedApplicabilityContext,
    resolve_governed_applicability,
)
from app.domain.rule_evaluation import (
    Observation,
    RuleComparisonOutcome,
    RuleRequirement,
    compare_rule,
)
from app.domain.rule_registry_types import (
    EvidenceReferenceDraft,
    MissingHandling,
    RuleCategory,
    RuleOperator,
    SafeDefault,
)
from app.domain.unit_policy import UnitPolicyContext
from app.domain.verification_types import (
    EvidenceVerificationAuthoritySnapshot,
    EvidenceVerificationDecisionDraft,
    EvidenceVerificationDelegationDraft,
    VerificationCapability,
    VerificationDelegationStatus,
    VerificationScopeSnapshot,
)
from app.models.digital_weld_passport import (
    DigitalWeldPassportLifecycleEvent,
    DigitalWeldPassportLifecycleState,
    DigitalWeldPassportRevision,
)
from app.models.entities import User
from app.models.governance import GovernedAuditEvent, GovernedCommandReceipt
from app.models.machine_readiness import (
    MachineReadinessAssessmentRevision,
    MachineReadinessCheckResult,
)
from app.models.rule_evaluation import RuleEvaluation
from app.models.rule_registry import (
    EngineeringRuleRevision,
    EvidenceReference,
    RuleLifecycleEvent,
    RuleLifecycleEventType,
)
from app.repositories.evidence_verification_repository import (
    EvidenceVerificationRepository,
)


RULE_ID = "PHASE_6A2_GOVERNED_INPUT_PRESENT"
RULE_REVISION = "1.0"
EVALUATION_ID = "phase-6a2-evaluation"
ASSESSMENT_ID = "phase-6a2-assessment"
PASSPORT_ID = "phase-6a2-passport"
PROJECT_SCOPE = {"project": "phase-6a2-project"}
# Canonical 4-dimension lifecycle scope: the governed enable/activate basis
# check requires exact equality with the verification authority resource_scope
# (VerificationScopeSnapshot.as_dict()), so lifecycle audits must pin the same
# canonical snapshot instead of the short project-only scope.
LIFECYCLE_SCOPE = VerificationScopeSnapshot(project=str(PROJECT_SCOPE["project"])).as_dict()
DECISION_TIME = datetime(2037, 1, 2, 12, 0, tzinfo=timezone.utc)
BASE_TIME = datetime(2037, 1, 1, 12, 0, tzinfo=timezone.utc)

ACTORS = {
    "submitter": {
        "email": "phase6a2-submitter@example.com",
        "name": "Phase 6A2 Submitter",
        "role": "Engineer",
    },
    "verifier": {
        "email": "phase6a2-verifier@example.com",
        "name": "Phase 6A2 Verifier",
        "role": "Verifier",
    },
    "approver": {
        "email": "phase6a2-approver@example.com",
        "name": "Phase 6A2 Approver",
        "role": "Approver",
    },
    "releaser": {
        "email": "phase6a2-releaser@example.com",
        "name": "Phase 6A2 Releaser",
        "role": "ReleaseAuthority",
    },
}


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode(
            "utf-8"
        )
    ).hexdigest()


def _request_hash(label: str) -> CanonicalRequestHash:
    return CanonicalRequestHash(
        value=_digest({"phase": "6A2", "command": label}),
        hash_algorithm="sha256",
        canonicalization_version="phase-6a2-canonical-v1",
    )


def _identity(namespace: str, scope: str, key: str) -> CommandIdentity:
    return CommandIdentity(
        command_namespace=namespace,
        command_scope=scope,
        idempotency_key=key,
    )


def _audit(
    event_id: str,
    *,
    actor: dict[str, object],
    actor_user_id: int,
    idempotency_key: str,
    reason: str,
    authority_scope: dict[str, object] = PROJECT_SCOPE,
) -> GovernedAuditMetadata:
    return GovernedAuditMetadata(
        event_id=event_id,
        actor_id=str(actor["email"]),
        actor_type="user",
        actor_user_id=actor_user_id,
        actor_role=str(actor["role"]),
        authority_scope=authority_scope,
        reason=reason,
        correlation_id=f"phase-6a2:{event_id}",
        idempotency_key=idempotency_key,
        schema_version="phase-6a2-v1",
        software_version="phase-6a2-test",
        canonicalization_version="phase-6a2-canonical-v1",
        hash_algorithm="sha256",
        detail={"phase": "6A2", "path": "governed-postgresql-happy-path"},
        created_at=BASE_TIME,
    )


def _seed_users(session: Session) -> dict[str, int]:
    users = {
        key: User(
            email=str(actor["email"]),
            full_name=str(actor["name"]),
            password_hash=f"hash-{key}",
            role=str(actor["role"]),
        )
        for key, actor in ACTORS.items()
    }
    session.add_all(users.values())
    session.flush()
    return {key: user.id for key, user in users.items()}


def _version_metadata() -> ContentVersionMetadata:
    return ContentVersionMetadata(
        schema_version="phase-6a2-registry-v1",
        canonicalization_version="phase-6a2-canonical-v1",
        hash_algorithm="sha256",
        content_hash=_digest({"rule_id": RULE_ID, "revision": RULE_REVISION}),
        software_version="phase-6a2-test",
    )


def _create_verified_evidence(
    session: Session,
    *,
    evidence_reference: EvidenceReference,
    verifier_user_id: int,
    verifier_role: str,
    grantor_user_id: int,
) -> None:
    repository = EvidenceVerificationRepository(session)
    scope = VerificationScopeSnapshot(project=str(PROJECT_SCOPE["project"]))
    delegation = repository.create_delegation_revision(
        draft=EvidenceVerificationDelegationDraft(
            delegation_id="phase-6a2-verification-delegation",
            revision_number=1,
            verifier_user_id=verifier_user_id,
            granted_by_user_id=grantor_user_id,
            scope_snapshot=scope,
            effective_from=BASE_TIME - timedelta(days=1),
            expires_at=None,
            revoked_by_user_id=None,
            revoked_at=None,
            revoked_reason=None,
            status=VerificationDelegationStatus.ACTIVE,
            capability=VerificationCapability.EVIDENCE_VERIFICATION,
            created_by_user_id=grantor_user_id,
            created_by_actor_id=str(ACTORS["approver"]["email"]),
            schema_version="phase-6a2-verification-v1",
            canonicalization_version="phase-6a2-canonical-v1",
            hash_algorithm="sha256",
            content_hash=_digest(
                {
                    "delegation_id": "phase-6a2-verification-delegation",
                    "verifier_user_id": verifier_user_id,
                    "scope": scope.as_dict(),
                }
            ),
            software_version="phase-6a2-test",
        )
    )
    authority_without_hash = EvidenceVerificationAuthoritySnapshot(
        verifier_user_id=verifier_user_id,
        verifier_role_snapshot=verifier_role,
        capability=VerificationCapability.EVIDENCE_VERIFICATION,
        resource_scope=scope,
        delegation_id=delegation.delegation_id,
        delegation_revision_number=delegation.revision_number,
        delegation_status=delegation.status,
        delegation_effective_from=delegation.effective_from,
        delegation_expires_at=delegation.expires_at,
        delegation_revoked_at=delegation.revoked_at,
        policy_identifier="SDS-115",
        policy_version="0.1 Draft",
        decision_at=BASE_TIME,
        correlation_id="phase-6a2-verification",
        schema_version="evidence-verification-authority-snapshot-v1",
        canonicalization_version="canonical-v1",
        hash_algorithm="sha256",
        content_hash="",
        software_version="phase-6a2-test",
    )
    authority = EvidenceVerificationAuthoritySnapshot(
        verifier_user_id=authority_without_hash.verifier_user_id,
        verifier_role_snapshot=authority_without_hash.verifier_role_snapshot,
        capability=authority_without_hash.capability,
        resource_scope=authority_without_hash.resource_scope,
        delegation_id=authority_without_hash.delegation_id,
        delegation_revision_number=authority_without_hash.delegation_revision_number,
        delegation_status=authority_without_hash.delegation_status,
        delegation_effective_from=authority_without_hash.delegation_effective_from,
        delegation_expires_at=authority_without_hash.delegation_expires_at,
        delegation_revoked_at=authority_without_hash.delegation_revoked_at,
        policy_identifier=authority_without_hash.policy_identifier,
        policy_version=authority_without_hash.policy_version,
        decision_at=authority_without_hash.decision_at,
        correlation_id=authority_without_hash.correlation_id,
        schema_version=authority_without_hash.schema_version,
        canonicalization_version=authority_without_hash.canonicalization_version,
        hash_algorithm=authority_without_hash.hash_algorithm,
        content_hash=_digest(authority_without_hash.as_dict()),
        software_version=authority_without_hash.software_version,
    )
    repository.create_verification_decision(
        draft=EvidenceVerificationDecisionDraft(
            verification_id="phase-6a2-evidence-verification",
            revision_number=1,
            evidence_reference_id=evidence_reference.id,
            evidence_verification_delegation_id=delegation.id,
            verifier_user_id=verifier_user_id,
            authority_snapshot=authority.as_dict(),
            decision_reason="Verified exact source-backed test evidence",
            decided_at=BASE_TIME,
            policy_identifier="SDS-115",
            policy_version="0.1 Draft",
            correlation_id="phase-6a2-verification",
            supersedes_verification_decision_id=None,
            created_by_user_id=verifier_user_id,
            created_by_actor_id=str(ACTORS["verifier"]["email"]),
            schema_version="phase-6a2-verification-v1",
            canonicalization_version="phase-6a2-canonical-v1",
            hash_algorithm="sha256",
            content_hash=_digest(
                {
                    "verification_id": "phase-6a2-evidence-verification",
                    "evidence_reference_id": evidence_reference.id,
                    "delegation_id": delegation.id,
                    "authority_hash": authority.content_hash,
                }
            ),
            software_version="phase-6a2-test",
        )
    )


def _transition_dwp(
    engine,
    *,
    state: DigitalWeldPassportLifecycleState,
    actor_name: str,
    actor_user_id: int,
    sequence: int,
    mrc_snapshot: dict[str, object],
):
    key = f"phase-6a2-dwp-{state.value.lower()}"
    identity = _identity(DigitalWeldPassportService.COMMAND_NAMESPACE, PASSPORT_ID, key)
    request_hash = _request_hash(key)
    audit = _audit(
        f"phase-6a2-dwp-{state.value.lower()}-audit",
        actor=ACTORS[actor_name],
        actor_user_id=actor_user_id,
        idempotency_key=key,
        reason=f"Advance governed passport to {state.value}",
    )
    with Session(engine) as session:
        revision = session.scalar(
            select(DigitalWeldPassportRevision).where(
                DigitalWeldPassportRevision.passport_id == PASSPORT_ID,
                DigitalWeldPassportRevision.revision_number == 1,
            )
        )
        assert revision is not None
        current = session.scalar(
            select(DigitalWeldPassportLifecycleEvent)
            .where(DigitalWeldPassportLifecycleEvent.passport_revision_id == revision.id)
            .order_by(DigitalWeldPassportLifecycleEvent.revision_number.desc())
        )
        assert current is not None
        transition = DigitalWeldPassportLifecycleTransitionDraft(
            passport_id=PASSPORT_ID,
            revision_number=1,
            state=state,
            reason=audit.reason,
            mrc_snapshot=mrc_snapshot,
            supersedes_lifecycle_event_id=current.id,
        )
        session.rollback()
        with GovernedUnitOfWork(session) as unit_of_work:
            result = DigitalWeldPassportService(unit_of_work).transition_revision(
                transition=transition,
                receipt_id=f"phase-6a2-dwp-transition-receipt-{sequence}",
                command_identity=identity,
                request_hash=request_hash,
                audit=audit,
                completed_at=BASE_TIME + timedelta(minutes=sequence),
            )
            assert result.result_type == "digital_weld_passport"
            unit_of_work.commit()
    return result, transition, identity, request_hash, audit


def _persistent_counts(session: Session) -> tuple[int, ...]:
    models = (
        RuleEvaluation,
        MachineReadinessAssessmentRevision,
        MachineReadinessCheckResult,
        DigitalWeldPassportRevision,
        DigitalWeldPassportLifecycleEvent,
        GovernedAuditEvent,
        GovernedCommandReceipt,
    )
    return tuple(session.scalar(select(func.count(model.id))) or 0 for model in models)


def test_governed_registry_to_production_active_passport_on_postgresql(
    postgresql_engine,
    monkeypatch,
) -> None:
    assert postgresql_engine.dialect.name == "postgresql"

    audit_ids = {
        "phase-6a2-rule-identity-audit",
        "phase-6a2-rule-revision-audit",
        "phase-6a2-rule-enable-audit",
        "phase-6a2-rule-activate-audit",
        "phase-6a2-evaluation-audit",
        "phase-6a2-mrc-audit",
        "phase-6a2-dwp-create-audit",
        "phase-6a2-dwp-engineering_defined-audit",
        "phase-6a2-dwp-validation_pending-audit",
        "phase-6a2-dwp-validated-audit",
        "phase-6a2-dwp-approved-audit",
        "phase-6a2-dwp-production_active-audit",
    }

    with Session(postgresql_engine) as session:
        user_ids = _seed_users(session)
        session.commit()
        with GovernedUnitOfWork(session) as unit_of_work:
            registry = RuleRegistryService(unit_of_work)
            registry.create_identity(
                rule_id=RULE_ID,
                audit=_audit(
                    "phase-6a2-rule-identity-audit",
                    actor=ACTORS["submitter"],
                    actor_user_id=user_ids["submitter"],
                    idempotency_key="phase-6a2-rule-identity",
                    reason="Create exact Phase 6A2 rule identity",
                ),
            )
            revision = registry.create_draft_revision(
                rule_id=RULE_ID,
                revision=RULE_REVISION,
                name="Governed binary input-presence requirement",
                evidence_class=EvidenceClass.SOURCE_BACKED,
                category=RuleCategory.OTHER,
                parameter="governed_input_present",
                safe_default=SafeDefault.UNRESOLVED,
                missing_handling=MissingHandling.DATA_INSUFFICIENT,
                reason_for_change="Create deterministic Phase 6A2 E2E revision",
                version_metadata=_version_metadata(),
                audit=_audit(
                    "phase-6a2-rule-revision-audit",
                    actor=ACTORS["submitter"],
                    actor_user_id=user_ids["submitter"],
                    idempotency_key="phase-6a2-rule-revision",
                    reason="Create exact source-backed rule revision",
                ),
                evidence_references=(
                    EvidenceReferenceDraft(
                        evidence_id="PHASE_6A2_E2E_EVIDENCE",
                        evidence_revision="1",
                        evidence_class=EvidenceClass.UNRESOLVED,
                        lifecycle_status=RuleLifecycleStatus.DRAFT,
                        created_by_actor_id=str(ACTORS["submitter"]["email"]),
                        created_by_user_id=user_ids["submitter"],
                        reference_uri="urn:spotweld-ai:test:phase-6a2",
                    ),
                ),
                allow_source_backed=True,
            )
            assert revision.revision == RULE_REVISION
            assert len(revision.evidence_references) == 1
            _create_verified_evidence(
                session,
                evidence_reference=revision.evidence_references[0],
                verifier_user_id=user_ids["verifier"],
                verifier_role=str(ACTORS["verifier"]["role"]),
                grantor_user_id=user_ids["approver"],
            )
            unit_of_work.commit()

        for event_type, namespace, minute in (
            (RuleLifecycleEventType.ENABLE, RuleRegistryService.ENABLEMENT_COMMAND_NAMESPACE, 1),
            (RuleLifecycleEventType.ACTIVATE, RuleRegistryService.ACTIVATION_COMMAND_NAMESPACE, 2),
        ):
            key = f"phase-6a2-rule-{event_type.value.lower()}"
            with GovernedUnitOfWork(session) as unit_of_work:
                registry = RuleRegistryService(unit_of_work)
                transition = (
                    registry.enable_source_backed
                    if event_type is RuleLifecycleEventType.ENABLE
                    else registry.activate_source_backed
                )
                transition_result = transition(
                    rule_id=RULE_ID,
                    source_revision=RULE_REVISION,
                    receipt_id=f"{key}-receipt",
                    command_identity=_identity(namespace, RULE_ID, key),
                    request_hash=_request_hash(key),
                    audit=_audit(
                        f"{key}-audit",
                        actor=ACTORS["approver"],
                        actor_user_id=user_ids["approver"],
                        idempotency_key=key,
                        reason=f"{event_type.value.title()} exact source-backed revision",
                        authority_scope=LIFECYCLE_SCOPE,
                    ),
                    effective_from=BASE_TIME,
                    expires_at=BASE_TIME + timedelta(days=30),
                    completed_at=BASE_TIME + timedelta(minutes=minute),
                )
                assert transition_result.result_type == "engineering_rule_lifecycle_event"
                unit_of_work.commit()

        revision_id = revision.id

    with Session(postgresql_engine) as session:
        active_revision = session.scalar(
            select(EngineeringRuleRevision).where(
                EngineeringRuleRevision.id == revision_id,
                EngineeringRuleRevision.revision == RULE_REVISION,
            )
        )
        activation = session.scalar(
            select(RuleLifecycleEvent).where(
                RuleLifecycleEvent.engineering_rule_revision_id == revision_id,
                RuleLifecycleEvent.event_type == RuleLifecycleEventType.ACTIVATE,
            )
        )
        assert active_revision is not None
        assert activation is not None
        assert activation.scope_snapshot == LIFECYCLE_SCOPE
        candidate = GovernedApplicabilityCandidate(
            candidate_id=f"{RULE_ID}:{RULE_REVISION}",
            rule_id=RULE_ID,
            revision=RULE_REVISION,
            evidence_class=active_revision.evidence_class,
            enabled=True,
            active=True,
            scope_snapshot={"project": [str(PROJECT_SCOPE["project"])]},
            effective_from=activation.effective_from,
            expires_at=activation.expires_at,
            basis_valid=bool(activation.basis_snapshot.get("content_hash")),
        )
        context = GovernedApplicabilityContext(project=str(PROJECT_SCOPE["project"]))
        applicability = resolve_governed_applicability(
            context,
            DECISION_TIME,
            (candidate,),
        )
        assert applicability.outcome is ApplicabilityResolutionOutcome.SELECTED
        assert applicability.selected_rule_id == RULE_ID
        assert applicability.selected_revision == RULE_REVISION

        unit_policy = UnitPolicyContext(expected_unit="binary")
        observation = Observation(
            parameter=active_revision.parameter,
            value=1.0,
            unit="binary",
        )
        comparison = compare_rule(
            RuleRequirement(
                rule_id=RULE_ID,
                revision=RULE_REVISION,
                parameter=active_revision.parameter,
                operator=RuleOperator.EQUALS,
                unit="binary",
                min_value=1.0,
                max_value=1.0,
            ),
            observation,
            applicability_result=applicability,
            unit_context=unit_policy,
        )
        assert comparison.outcome is RuleComparisonOutcome.SATISFIED
        session.rollback()

        evaluation_identity = _identity(
            RuleEvaluationService.COMMAND_NAMESPACE,
            EVALUATION_ID,
            "phase-6a2-evaluation",
        )
        evaluation_hash = _request_hash("phase-6a2-evaluation")
        with GovernedUnitOfWork(session) as unit_of_work:
            result = RuleEvaluationService(unit_of_work).persist_evaluation(
                draft=RuleEvaluationPersistenceDraft(
                    evaluation_id=EVALUATION_ID,
                    revision_number=1,
                    comparison=comparison,
                    applicability_result=applicability,
                    observation=observation,
                    unit_context=unit_policy,
                ),
                receipt_id="phase-6a2-evaluation-receipt",
                command_identity=evaluation_identity,
                request_hash=evaluation_hash,
                audit=_audit(
                    "phase-6a2-evaluation-audit",
                    actor=ACTORS["submitter"],
                    actor_user_id=user_ids["submitter"],
                    idempotency_key="phase-6a2-evaluation",
                    reason="Persist exact selected rule-revision evaluation",
                ),
                completed_at=BASE_TIME + timedelta(minutes=3),
            )
            assert result.result_type == "rule_evaluation"
            assert result.result_id == EVALUATION_ID
            assert result.result_revision == "1"
            unit_of_work.commit()

        evaluation = session.scalar(
            select(RuleEvaluation).where(
                RuleEvaluation.evaluation_id == EVALUATION_ID,
                RuleEvaluation.revision_number == 1,
            )
        )
        assert evaluation is not None
        assert evaluation.engineering_rule_revision_id == revision_id
        assert evaluation.rule_id == RULE_ID
        assert evaluation.rule_revision == RULE_REVISION
        assert evaluation.outcome is RuleComparisonOutcome.SATISFIED

        check = GovernedMachineReadinessCheck(
            check_id="governed-input-present",
            required=True,
            evaluations=(
                GovernedRuleEvaluationSnapshot(
                    evaluation_id=EVALUATION_ID,
                    revision_number=1,
                    comparison=comparison,
                ),
            ),
            description="Exact governed binary input-presence evaluation",
        )
        readiness = evaluate_machine_readiness(context, DECISION_TIME, (check,))
        assert readiness.state is ReadinessState.READY
        assert readiness.validated_applicable_basis_count == 1
        session.rollback()

        mrc_identity = _identity(
            MachineReadinessService.COMMAND_NAMESPACE,
            ASSESSMENT_ID,
            "phase-6a2-mrc",
        )
        mrc_hash = _request_hash("phase-6a2-mrc")
        mrc_draft = MachineReadinessPersistenceDraft(
            assessment_id=ASSESSMENT_ID,
            revision_number=1,
            result=readiness,
            checks=(check,),
        )
        with GovernedUnitOfWork(session) as unit_of_work:
            mrc_result = MachineReadinessService(unit_of_work).persist_assessment(
                draft=mrc_draft,
                receipt_id="phase-6a2-mrc-receipt",
                command_identity=mrc_identity,
                request_hash=mrc_hash,
                audit=_audit(
                    "phase-6a2-mrc-audit",
                    actor=ACTORS["submitter"],
                    actor_user_id=user_ids["submitter"],
                    idempotency_key="phase-6a2-mrc",
                    reason="Persist READY result from exact evaluation revision",
                ),
                completed_at=BASE_TIME + timedelta(minutes=4),
            )
            assert mrc_result.result_type == "machine_readiness"
            assert mrc_result.result_id == ASSESSMENT_ID
            assert mrc_result.result_revision == "1"
            unit_of_work.commit()

        mrc_revision = session.scalar(
            select(MachineReadinessAssessmentRevision).where(
                MachineReadinessAssessmentRevision.assessment_id == ASSESSMENT_ID,
                MachineReadinessAssessmentRevision.revision_number == 1,
            )
        )
        mrc_check = session.scalar(
            select(MachineReadinessCheckResult).where(
                MachineReadinessCheckResult.assessment_revision_id == mrc_revision.id
            )
        ) if mrc_revision is not None else None
        assert mrc_revision is not None
        assert mrc_revision.state is ReadinessState.READY
        assert mrc_revision.validated_applicable_basis_count == 1
        assert mrc_check is not None
        pinned_evaluation = mrc_check.check_snapshot["evaluations"][0]
        assert pinned_evaluation["evaluation_id"] == EVALUATION_ID
        assert pinned_evaluation["revision_number"] == 1

        mrc_snapshot = DigitalWeldPassportService._mrc_snapshot(mrc_revision)
        evaluation_snapshot = DigitalWeldPassportService._rule_evaluation_snapshot(
            evaluation
        )
        session.rollback()

        dwp_identity = _identity(
            DigitalWeldPassportService.COMMAND_NAMESPACE,
            PASSPORT_ID,
            "phase-6a2-dwp-create",
        )
        dwp_hash = _request_hash("phase-6a2-dwp-create")
        dwp_audit = _audit(
            "phase-6a2-dwp-create-audit",
            actor=ACTORS["submitter"],
            actor_user_id=user_ids["submitter"],
            idempotency_key="phase-6a2-dwp-create",
            reason="Create DWP draft from exact READY MRC revision",
        )
        with GovernedUnitOfWork(session) as unit_of_work:
            dwp_result = DigitalWeldPassportService(unit_of_work).create_draft_revision(
                draft=DigitalWeldPassportRevisionDraft(
                    passport_id=PASSPORT_ID,
                    revision_number=1,
                    context_snapshot={
                        "passport_id": PASSPORT_ID,
                        "weld_identity": {
                            "project": PROJECT_SCOPE["project"],
                            "site": "phase-6a2-site",
                            "machine": "phase-6a2-machine",
                        },
                        "scope_snapshot": PROJECT_SCOPE,
                    },
                    provenance_snapshot={
                        "rule_evaluations": [evaluation_snapshot],
                    },
                    authority_snapshot={"scope_snapshot": PROJECT_SCOPE},
                    mrc_snapshot=mrc_snapshot,
                ),
                receipt_id="phase-6a2-dwp-create-receipt",
                command_identity=dwp_identity,
                request_hash=dwp_hash,
                audit=dwp_audit,
                completed_at=BASE_TIME + timedelta(minutes=5),
            )
            assert dwp_result.result_type == "digital_weld_passport"
            assert dwp_result.result_id == PASSPORT_ID
            assert dwp_result.result_revision == "1"
            unit_of_work.commit()

    lifecycle = (
        (DigitalWeldPassportLifecycleState.ENGINEERING_DEFINED, "submitter"),
        (DigitalWeldPassportLifecycleState.VALIDATION_PENDING, "submitter"),
        (DigitalWeldPassportLifecycleState.VALIDATED, "verifier"),
        (DigitalWeldPassportLifecycleState.APPROVED, "approver"),
        (DigitalWeldPassportLifecycleState.PRODUCTION_ACTIVE, "releaser"),
    )
    final_call = None
    for sequence, (state, actor_name) in enumerate(lifecycle, start=6):
        final_call = _transition_dwp(
            postgresql_engine,
            state=state,
            actor_name=actor_name,
            actor_user_id=user_ids[actor_name],
            sequence=sequence,
            mrc_snapshot=mrc_snapshot,
        )
    assert final_call is not None
    final_result, final_transition, final_identity, final_hash, final_audit = final_call

    with Session(postgresql_engine) as session:
        dwp_revision = session.scalar(
            select(DigitalWeldPassportRevision).where(
                DigitalWeldPassportRevision.passport_id == PASSPORT_ID,
                DigitalWeldPassportRevision.revision_number == 1,
            )
        )
        assert dwp_revision is not None
        assert dwp_revision.mrc_snapshot["assessment_id"] == ASSESSMENT_ID
        assert dwp_revision.mrc_snapshot["revision_number"] == 1
        assert dwp_revision.mrc_snapshot["state"] == ReadinessState.READY.value
        assert dwp_revision.provenance_snapshot["rule_evaluations"][0][
            "evaluation_id"
        ] == EVALUATION_ID
        assert dwp_revision.provenance_snapshot["rule_evaluations"][0][
            "revision_number"
        ] == 1
        states = list(
            session.scalars(
                select(DigitalWeldPassportLifecycleEvent.state)
                .where(
                    DigitalWeldPassportLifecycleEvent.passport_revision_id
                    == dwp_revision.id
                )
                .order_by(DigitalWeldPassportLifecycleEvent.revision_number)
            )
        )
        assert states == [
            DigitalWeldPassportLifecycleState.DRAFT,
            *(state for state, _actor_name in lifecycle),
        ]
        persisted_audits = set(
            session.scalars(
                select(GovernedAuditEvent.event_id).where(
                    GovernedAuditEvent.event_id.in_(audit_ids)
                )
            )
        )
        assert persisted_audits == audit_ids
        counts_before_replay = _persistent_counts(session)
        session.rollback()

    with Session(postgresql_engine) as session, GovernedUnitOfWork(session) as unit_of_work:
        replay = DigitalWeldPassportService(unit_of_work).transition_revision(
            transition=final_transition,
            receipt_id="unused-phase-6a2-replay-receipt",
            command_identity=final_identity,
            request_hash=final_hash,
            audit=final_audit,
            completed_at=BASE_TIME + timedelta(minutes=30),
        )
        assert replay == final_result

    with Session(postgresql_engine) as session:
        assert _persistent_counts(session) == counts_before_replay
        read_actor = session.get(User, user_ids["submitter"])
        assert read_actor is not None
        session.rollback()

    def _unexpected_recompute(*_args, **_kwargs):
        raise AssertionError("governed GET path recomputed an engineering result")

    monkeypatch.setattr(rule_evaluation_domain, "compare_rule", _unexpected_recompute)
    monkeypatch.setattr(readiness_domain, "evaluate_machine_readiness", _unexpected_recompute)
    isolated_session_factory = sessionmaker(bind=postgresql_engine)
    monkeypatch.setattr(mrc_api, "SessionLocal", isolated_session_factory)
    monkeypatch.setattr(dwp_api, "SessionLocal", isolated_session_factory)

    mrc_response = mrc_api.get_machine_readiness_revision(
        ASSESSMENT_ID,
        1,
        actor=read_actor,
    )
    assert mrc_response.decision_outcome == ReadinessState.READY.value
    assert mrc_response.result_id == ASSESSMENT_ID
    assert mrc_response.result_revision == "1"
    dwp_response = dwp_api.get_digital_weld_passport_revision(
        PASSPORT_ID,
        1,
        actor=read_actor,
    )
    assert dwp_response.state is DigitalWeldPassportLifecycleState.PRODUCTION_ACTIVE
    assert dwp_response.mrc_snapshot["assessment_id"] == ASSESSMENT_ID
    assert dwp_response.mrc_snapshot["revision_number"] == 1

    with Session(postgresql_engine) as session:
        assert _persistent_counts(session) == counts_before_replay
