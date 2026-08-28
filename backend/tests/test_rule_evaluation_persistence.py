"""Tests for governed persistence of pure rule-evaluation results."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

import app.domain.rule_evaluation as rule_evaluation_module
from app.application.governed_unit_of_work import GovernedUnitOfWork
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
from app.domain.idempotency_types import (
    CanonicalRequestHash,
    CommandIdentity,
)
from app.domain.rule_applicability import (
    ApplicabilityResolutionOutcome,
    GovernedApplicabilityCandidate,
    GovernedApplicabilityContext,
    GovernedApplicabilityResolution,
    resolve_governed_applicability,
)
from app.domain.rule_evaluation import (
    Observation,
    RuleComparison,
    RuleComparisonOutcome,
    RuleRequirement,
    compare_rule,
)
from app.domain.rule_registry_types import (
    MissingHandling,
    RuleCategory,
    RuleOperator,
    SafeDefault,
)
from app.domain.unit_policy import UnitPolicyCatalog, UnitPolicyContext
from app.models.governance import GovernedAuditEvent, GovernedCommandReceipt
from app.models.rule_evaluation import RuleEvaluation
from app.models.rule_registry import EngineeringRuleRevision
from app.repositories.governance_repository import GovernanceRepository
from app.repositories.rule_evaluation_repository import RuleEvaluationRepository

RULE_ID = "PERSISTED_EVALUATION_RULE"
RULE_REVISION = "1.0"
DECISION_TIME = datetime(2034, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
AUDIT_TIME = datetime(2034, 1, 2, 3, 4, 6, tzinfo=timezone.utc)
EVALUATION_ID = "evaluation-1"
RECEIPT_ID = "receipt-1"


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


def _audit(event_id: str, *, reason: str = "Synthetic persistence test") -> GovernedAuditMetadata:
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


def _seed_rule(session: Session, *, revision: str = RULE_REVISION) -> EngineeringRuleRevision:
    with GovernedUnitOfWork(session) as unit_of_work:
        service = RuleRegistryService(unit_of_work)
        service.create_identity(rule_id=RULE_ID, audit=_audit(f"{revision}-identity"))
        created = service.create_draft_revision(
            rule_id=RULE_ID,
            revision=revision,
            name="Synthetic persisted evaluation rule",
            evidence_class=EvidenceClass.UNRESOLVED,
            category=RuleCategory.OTHER,
            parameter="synthetic_parameter",
            safe_default=SafeDefault.UNRESOLVED,
            missing_handling=MissingHandling.DATA_INSUFFICIENT,
            reason_for_change="Synthetic persisted evaluation seed",
            version_metadata=_version(revision),
            audit=_audit(f"{revision}-revision"),
            enabled=False,
        )
        unit_of_work.commit()
        return created


def _selected_resolution(
    *,
    rule_id: str = RULE_ID,
    revision: str = RULE_REVISION,
) -> GovernedApplicabilityResolution:
    candidate = GovernedApplicabilityCandidate(
        candidate_id=f"{rule_id}:{revision}",
        rule_id=rule_id,
        revision=revision,
        evidence_class=EvidenceClass.SOURCE_BACKED,
        enabled=True,
        active=True,
        scope_snapshot={"customer": ["customer-a"]},
        effective_from=datetime(2034, 1, 1, 0, 0, tzinfo=timezone.utc),
    )
    return resolve_governed_applicability(
        GovernedApplicabilityContext(customer="customer-a"),
        DECISION_TIME,
        [candidate],
    )


def _comparison(
    requirement: RuleRequirement,
    observation: Observation | None,
    *,
    applicability_result: GovernedApplicabilityResolution,
    unit_context: UnitPolicyContext | None = None,
    unit_catalog: UnitPolicyCatalog | None = None,
) -> RuleComparison:
    return compare_rule(
        requirement,
        observation,
        applicability_result=applicability_result,
        unit_context=unit_context,
        unit_catalog=unit_catalog,
    )


def _persist(
    session: Session,
    *,
    comparison: RuleComparison,
    applicability_result: GovernedApplicabilityResolution,
    observation: Observation | None,
    unit_context: UnitPolicyContext | None = None,
    unit_catalog: UnitPolicyCatalog | None = None,
    evaluation_id: str = EVALUATION_ID,
    revision_number: int = 1,
    supersedes_evaluation_id: int | None = None,
    receipt_id: str = RECEIPT_ID,
    idempotency_key: str = "synthetic-idempotency-key",
    request_payload: str = "same-request",
    audit_event_id: str = "evaluation-persist-event",
    expected_result_type: str = "rule_evaluation",
) -> tuple[RuleEvaluation | None, GovernedCommandReceipt, GovernedAuditEvent]:
    draft = RuleEvaluationPersistenceDraft(
        evaluation_id=evaluation_id,
        revision_number=revision_number,
        comparison=comparison,
        applicability_result=applicability_result,
        observation=observation,
        unit_context=unit_context,
        unit_catalog=unit_catalog,
        supersedes_evaluation_id=supersedes_evaluation_id,
    )
    command_identity = CommandIdentity(
        command_namespace=RuleEvaluationService.COMMAND_NAMESPACE,
        command_scope=evaluation_id,
        idempotency_key=idempotency_key,
    )
    request_hash = CanonicalRequestHash(
        value=hashlib.sha256(request_payload.encode("utf-8")).hexdigest(),
        hash_algorithm="sha256",
        canonicalization_version="persistence-canonical-v1",
    )
    audit = _audit(audit_event_id)
    if session.in_transaction():
        session.rollback()
    with GovernedUnitOfWork(session) as unit_of_work:
        service = RuleEvaluationService(unit_of_work)
        result = service.persist_evaluation(
            draft=draft,
            receipt_id=receipt_id,
            command_identity=command_identity,
            request_hash=request_hash,
            audit=audit,
            completed_at=AUDIT_TIME,
        )
        assert result.result_type == expected_result_type
        unit_of_work.commit()

    persisted = session.scalar(
        select(RuleEvaluation).where(
            RuleEvaluation.evaluation_id == evaluation_id,
            RuleEvaluation.revision_number == revision_number,
        )
    )
    receipt = session.scalar(
        select(GovernedCommandReceipt).where(
            GovernedCommandReceipt.command_namespace
            == RuleEvaluationService.COMMAND_NAMESPACE,
            GovernedCommandReceipt.command_scope == evaluation_id,
            GovernedCommandReceipt.idempotency_key == command_identity.idempotency_key,
        )
    )
    audit_event = GovernanceRepository(session).get_by_event_id(audit_event_id)
    if expected_result_type == "rule_evaluation":
        assert persisted is not None
    else:
        assert persisted is None
    assert receipt is not None
    assert audit_event is not None
    return persisted, receipt, audit_event


def test_persists_all_allowed_outcomes_and_preserves_provenance(persistence_engine):
    cases = [
        (
            RuleOperator.MIN,
            Observation("synthetic_parameter", 11.0, "synthetic_unit"),
            Observation("synthetic_parameter", 11.0, "synthetic_unit"),
            RuleComparisonOutcome.SATISFIED,
            None,
            10.0,
        ),
        (
            RuleOperator.MIN,
            Observation("synthetic_parameter", 9.0, "synthetic_unit"),
            Observation("synthetic_parameter", 9.0, "synthetic_unit"),
            RuleComparisonOutcome.NOT_SATISFIED,
            None,
            10.0,
        ),
        (
            RuleOperator.MIN,
            None,
            None,
            RuleComparisonOutcome.UNRESOLVED,
            None,
            10.0,
        ),
        (
            RuleOperator.MIN,
            Observation("synthetic_parameter", 11.0, "other_unit"),
            Observation("synthetic_parameter", 11.0, "other_unit"),
            RuleComparisonOutcome.UNIT_MISMATCH,
            UnitPolicyContext(expected_unit="synthetic_unit"),
            10.0,
        ),
        (
            RuleOperator.MIN,
            None,
            None,
            RuleComparisonOutcome.NOT_APPLICABLE,
            None,
            10.0,
        ),
    ]

    with Session(persistence_engine) as session:
        _seed_rule(session)
        selected = _selected_resolution()
        for index, (
            operator,
            comparison_observation,
            persist_observation,
            expected_outcome,
            unit_context,
            min_value,
        ) in enumerate(cases, start=1):
            requirement = RuleRequirement(
                rule_id=RULE_ID,
                revision=RULE_REVISION,
                parameter="synthetic_parameter",
                operator=operator,
                unit="synthetic_unit",
                min_value=min_value,
                enabled=expected_outcome is not RuleComparisonOutcome.NOT_APPLICABLE,
            )
            comparison = _comparison(
                requirement,
                comparison_observation,
                applicability_result=selected,
                unit_context=unit_context,
            )
            persisted, receipt, audit_event = _persist(
                session,
                comparison=comparison,
                applicability_result=selected,
                observation=persist_observation,
                unit_context=unit_context or UnitPolicyContext(expected_unit="synthetic_unit"),
                evaluation_id=f"{EVALUATION_ID}-{index}",
                receipt_id=f"{RECEIPT_ID}-{index}",
                audit_event_id=f"persist-event-{index}",
            )
            assert persisted.outcome is expected_outcome
            assert persisted.rule_id == RULE_ID
            assert persisted.rule_revision == RULE_REVISION
            assert persisted.applicability_snapshot["selected_rule_id"] == RULE_ID
            assert persisted.applicability_snapshot["selected_revision"] == RULE_REVISION
            assert persisted.observation_snapshot["parameter"] == (
                persist_observation.parameter if persist_observation is not None else None
            )
            assert persisted.observation_snapshot["value"] == (
                persist_observation.value if persist_observation is not None else None
            )
            assert persisted.observation_snapshot["unit"] == (
                persist_observation.unit if persist_observation is not None else None
            )
            assert persisted.result_snapshot["outcome"] == expected_outcome.value
            assert persisted.result_snapshot["rule_id"] == RULE_ID
            assert persisted.result_snapshot["revision"] == RULE_REVISION
            assert persisted.result_snapshot["applicability_result"]["selected_rule_id"] == RULE_ID
            assert persisted.result_snapshot["conversion_provenance"]["target_unit"] == "synthetic_unit"
            assert receipt.status.value == "COMPLETED"
            assert receipt.result_type == "rule_evaluation"
            assert audit_event.action == "PERSIST_RULE_EVALUATION"


def test_exact_pins_and_selection_requirements_fail_closed(persistence_engine):
    with Session(persistence_engine) as session:
        _seed_rule(session)
        selected = _selected_resolution()
        requirement = RuleRequirement(
            rule_id=RULE_ID,
            revision=RULE_REVISION,
            parameter="synthetic_parameter",
            operator=RuleOperator.MIN,
            unit="synthetic_unit",
            min_value=10.0,
        )
        comparison = _comparison(
            requirement,
            Observation("synthetic_parameter", 11.0, "synthetic_unit"),
            applicability_result=selected,
            unit_context=UnitPolicyContext(expected_unit="synthetic_unit"),
        )
        mismatched_selected = GovernedApplicabilityResolution(
            outcome=ApplicabilityResolutionOutcome.CONFLICT,
            reason="synthetic conflict",
            decision_time=DECISION_TIME,
            context=selected.context,
            candidates=selected.candidates,
            conflict_candidate_ids=("other",),
        )

        with GovernedUnitOfWork(session) as unit_of_work:
            service = RuleEvaluationService(unit_of_work)
            result = service.persist_evaluation(
                draft=RuleEvaluationPersistenceDraft(
                    evaluation_id="pin-mismatch",
                    revision_number=1,
                    comparison=comparison,
                    applicability_result=mismatched_selected,
                    observation=Observation("synthetic_parameter", 11.0, "synthetic_unit"),
                    unit_context=UnitPolicyContext(expected_unit="synthetic_unit"),
                ),
                receipt_id="receipt-pin-mismatch",
                command_identity=CommandIdentity(
                    command_namespace=RuleEvaluationService.COMMAND_NAMESPACE,
                    command_scope="pin-mismatch",
                    idempotency_key="synthetic-idempotency-key",
                ),
                request_hash=CanonicalRequestHash(
                    value=hashlib.sha256(b"pin-mismatch").hexdigest(),
                    hash_algorithm="sha256",
                    canonicalization_version="persistence-canonical-v1",
                ),
                audit=_audit("pin-mismatch-event"),
                completed_at=AUDIT_TIME,
            )
            assert result.result_type == "rule_evaluation_denial"
            unit_of_work.commit()

        assert session.scalar(
            select(RuleEvaluation).where(RuleEvaluation.evaluation_id == "pin-mismatch")
        ) is None
        assert GovernanceRepository(session).get_by_event_id("pin-mismatch-event") is not None
        assert session.scalar(
            select(GovernedCommandReceipt).where(
                GovernedCommandReceipt.command_scope == "pin-mismatch"
            )
        ) is not None
        session.rollback()

        mismatched_rule = GovernedApplicabilityResolution(
            outcome=ApplicabilityResolutionOutcome.SELECTED,
            reason="synthetic selection",
            decision_time=DECISION_TIME,
            context=selected.context,
            candidates=selected.candidates,
            selected_candidate_id=selected.selected_candidate_id,
            selected_rule_id="OTHER_RULE",
            selected_revision=RULE_REVISION,
            selected_specificity=selected.selected_specificity,
        )
        with GovernedUnitOfWork(session) as unit_of_work:
            service = RuleEvaluationService(unit_of_work)
            result = service.persist_evaluation(
                draft=RuleEvaluationPersistenceDraft(
                    evaluation_id="rule-pin-mismatch",
                    revision_number=1,
                    comparison=comparison,
                    applicability_result=mismatched_rule,
                    observation=Observation("synthetic_parameter", 11.0, "synthetic_unit"),
                    unit_context=UnitPolicyContext(expected_unit="synthetic_unit"),
                ),
                receipt_id="receipt-rule-pin-mismatch",
                command_identity=CommandIdentity(
                    command_namespace=RuleEvaluationService.COMMAND_NAMESPACE,
                    command_scope="rule-pin-mismatch",
                    idempotency_key="synthetic-idempotency-key",
                ),
                request_hash=CanonicalRequestHash(
                    value=hashlib.sha256(b"rule-pin-mismatch").hexdigest(),
                    hash_algorithm="sha256",
                    canonicalization_version="persistence-canonical-v1",
                ),
                audit=_audit("rule-pin-mismatch-event"),
                completed_at=AUDIT_TIME,
            )
            assert result.result_type == "rule_evaluation_denial"
            unit_of_work.commit()

        assert session.scalar(
            select(RuleEvaluation).where(
                RuleEvaluation.evaluation_id == "rule-pin-mismatch"
            )
        ) is None
        assert GovernanceRepository(session).get_by_event_id("rule-pin-mismatch-event") is not None


def test_persistence_service_does_not_recompute_and_preserves_conversion_provenance(
    persistence_engine,
    monkeypatch,
):
    with Session(persistence_engine) as session:
        _seed_rule(session)
        selected = _selected_resolution()
        requirement = RuleRequirement(
            rule_id=RULE_ID,
            revision=RULE_REVISION,
            parameter="synthetic_parameter",
            operator=RuleOperator.MIN,
            unit="synthetic_unit",
            min_value=10.0,
        )
        unit_context = UnitPolicyContext(
            expected_unit="synthetic_unit",
            conversion_factors={("raw_unit", "synthetic_unit"): 0.5},
            policy_version=_version("conversion"),
            rounding_policy="NO_ROUNDING",
        )
        comparison = _comparison(
            requirement,
            Observation("synthetic_parameter", 30.0, "raw_unit"),
            applicability_result=selected,
            unit_context=unit_context,
        )
        monkeypatch.setattr(
            rule_evaluation_module,
            "compare_rule",
            lambda *_args, **_kwargs: pytest.fail("persistence service must not recompute"),
        )
        persisted, receipt, _audit_event = _persist(
            session,
            comparison=comparison,
            applicability_result=selected,
            observation=Observation("synthetic_parameter", 30.0, "raw_unit"),
            unit_context=unit_context,
            evaluation_id="conversion-evaluation",
            receipt_id="conversion-receipt",
            audit_event_id="conversion-audit",
        )
        assert persisted.compared_value == pytest.approx(15.0)
        assert persisted.result_snapshot["conversion_provenance"]["conversion_occurred"] is True
        assert persisted.result_snapshot["conversion_provenance"]["factor"] == 0.5
        assert persisted.result_snapshot["conversion_provenance"]["original_unit"] == "raw_unit"
        assert persisted.result_snapshot["conversion_provenance"]["target_unit"] == "synthetic_unit"
        assert receipt.result_revision == "1"


def test_revision_corrections_supersede_only_the_latest_revision(persistence_engine):
    with Session(persistence_engine) as session:
        _seed_rule(session)
        selected = _selected_resolution()
        requirement = RuleRequirement(
            rule_id=RULE_ID,
            revision=RULE_REVISION,
            parameter="synthetic_parameter",
            operator=RuleOperator.MIN,
            unit="synthetic_unit",
            min_value=10.0,
        )
        first_comparison = _comparison(
            requirement,
            Observation("synthetic_parameter", 11.0, "synthetic_unit"),
            applicability_result=selected,
            unit_context=UnitPolicyContext(expected_unit="synthetic_unit"),
        )
        first, _, _ = _persist(
            session,
            comparison=first_comparison,
            applicability_result=selected,
            observation=Observation("synthetic_parameter", 11.0, "synthetic_unit"),
            unit_context=UnitPolicyContext(expected_unit="synthetic_unit"),
            evaluation_id="correction-evaluation",
            revision_number=1,
            receipt_id="correction-receipt-1",
            idempotency_key="correction-key-1",
            request_payload="correction-request-1",
            audit_event_id="correction-event-1",
        )
        correction_comparison = _comparison(
            requirement,
            Observation("synthetic_parameter", 12.0, "synthetic_unit"),
            applicability_result=selected,
            unit_context=UnitPolicyContext(expected_unit="synthetic_unit"),
        )
        corrected, _, _ = _persist(
            session,
            comparison=correction_comparison,
            applicability_result=selected,
            observation=Observation("synthetic_parameter", 12.0, "synthetic_unit"),
            unit_context=UnitPolicyContext(expected_unit="synthetic_unit"),
            evaluation_id="correction-evaluation",
            revision_number=2,
            supersedes_evaluation_id=first.id,
            receipt_id="correction-receipt-2",
            idempotency_key="correction-key-2",
            request_payload="correction-request-2",
            audit_event_id="correction-event-2",
        )
        assert corrected.revision_number == 2
        assert corrected.supersedes_evaluation_id == first.id
        history = RuleEvaluationRepository(session).list_history("correction-evaluation")
        assert [item.revision_number for item in history] == [1, 2]
        assert history[0].reason == first.reason

        denied_branch, branch_receipt, branch_audit = _persist(
            session,
            comparison=correction_comparison,
            applicability_result=selected,
            observation=Observation("synthetic_parameter", 12.0, "synthetic_unit"),
            unit_context=UnitPolicyContext(expected_unit="synthetic_unit"),
            evaluation_id="correction-evaluation",
            revision_number=3,
            supersedes_evaluation_id=first.id,
            receipt_id="correction-receipt-3",
            idempotency_key="correction-key-3",
            request_payload="correction-request-3",
            audit_event_id="correction-event-3",
            expected_result_type="rule_evaluation_denial",
        )
        assert denied_branch is None
        assert branch_receipt.result_type == "rule_evaluation_denial"
        assert branch_audit.action == "PERSIST_RULE_EVALUATION_DENIED"

        denied_sequence, sequence_receipt, sequence_audit = _persist(
            session,
            comparison=correction_comparison,
            applicability_result=selected,
            observation=Observation("synthetic_parameter", 12.0, "synthetic_unit"),
            unit_context=UnitPolicyContext(expected_unit="synthetic_unit"),
            evaluation_id="correction-evaluation",
            revision_number=4,
            supersedes_evaluation_id=corrected.id,
            receipt_id="correction-receipt-4",
            idempotency_key="correction-key-4",
            request_payload="correction-request-4",
            audit_event_id="correction-event-4",
            expected_result_type="rule_evaluation_denial",
        )
        assert denied_sequence is None
        assert sequence_receipt.result_type == "rule_evaluation_denial"
        assert sequence_audit.action == "PERSIST_RULE_EVALUATION_DENIED"


def test_idempotency_new_replay_conflict_and_in_progress(
    persistence_engine,
):
    with Session(persistence_engine) as setup_session:
        _seed_rule(setup_session)
        selected = _selected_resolution()
        requirement = RuleRequirement(
            rule_id=RULE_ID,
            revision=RULE_REVISION,
            parameter="synthetic_parameter",
            operator=RuleOperator.MIN,
            unit="synthetic_unit",
            min_value=10.0,
        )
        comparison = _comparison(
            requirement,
            Observation("synthetic_parameter", 11.0, "synthetic_unit"),
            applicability_result=selected,
            unit_context=UnitPolicyContext(expected_unit="synthetic_unit"),
        )
        first, receipt, _ = _persist(
            setup_session,
            comparison=comparison,
            applicability_result=selected,
            observation=Observation("synthetic_parameter", 11.0, "synthetic_unit"),
            unit_context=UnitPolicyContext(expected_unit="synthetic_unit"),
            evaluation_id="idempotent-evaluation",
            receipt_id="idempotent-receipt-1",
            audit_event_id="idempotent-audit-1",
        )
        assert receipt.status.value == "COMPLETED"
        assert first.revision_number == 1

    with Session(persistence_engine) as replay_session, GovernedUnitOfWork(
        replay_session
    ) as unit_of_work:
        service = RuleEvaluationService(unit_of_work)
        replay = service.persist_evaluation(
            draft=RuleEvaluationPersistenceDraft(
                evaluation_id="idempotent-evaluation",
                revision_number=1,
                comparison=comparison,
                applicability_result=selected,
                observation=Observation("synthetic_parameter", 11.0, "synthetic_unit"),
                unit_context=UnitPolicyContext(expected_unit="synthetic_unit"),
            ),
            receipt_id="unused-replay-receipt",
            command_identity=CommandIdentity(
                command_namespace=RuleEvaluationService.COMMAND_NAMESPACE,
                command_scope="idempotent-evaluation",
                idempotency_key="synthetic-idempotency-key",
            ),
            request_hash=CanonicalRequestHash(
                value=hashlib.sha256(b"same-request").hexdigest(),
                hash_algorithm="sha256",
                canonicalization_version="persistence-canonical-v1",
            ),
            audit=_audit("idempotent-audit-replay"),
            completed_at=AUDIT_TIME,
        )
        assert replay.result_type == "rule_evaluation"
        unit_of_work.commit()

    with Session(persistence_engine) as conflict_session, pytest.raises(
        ValueError, match="idempotency conflict"
    ), GovernedUnitOfWork(conflict_session) as unit_of_work:
        service = RuleEvaluationService(unit_of_work)
        service.persist_evaluation(
            draft=RuleEvaluationPersistenceDraft(
                evaluation_id="idempotent-evaluation",
                revision_number=1,
                comparison=comparison,
                applicability_result=selected,
                observation=Observation("synthetic_parameter", 11.0, "synthetic_unit"),
                unit_context=UnitPolicyContext(expected_unit="synthetic_unit"),
            ),
            receipt_id="unused-conflict-receipt",
            command_identity=CommandIdentity(
                command_namespace=RuleEvaluationService.COMMAND_NAMESPACE,
                command_scope="idempotent-evaluation",
                idempotency_key="synthetic-idempotency-key",
            ),
            request_hash=CanonicalRequestHash(
                value=hashlib.sha256(b"different-request").hexdigest(),
                hash_algorithm="sha256",
                canonicalization_version="persistence-canonical-v1",
            ),
            audit=_audit("idempotent-audit-conflict"),
            completed_at=AUDIT_TIME,
        )

    with Session(persistence_engine) as reserved_session, GovernedUnitOfWork(
        reserved_session
    ) as unit_of_work:
        service = RuleEvaluationService(unit_of_work)
        service._idempotency.reserve_or_inspect(
            receipt_id="idempotent-receipt-2",
            identity=CommandIdentity(
                command_namespace=RuleEvaluationService.COMMAND_NAMESPACE,
                command_scope="in-progress-evaluation",
                idempotency_key="in-progress-key",
            ),
            request_hash=CanonicalRequestHash(
                value=hashlib.sha256(b"pending-request").hexdigest(),
                hash_algorithm="sha256",
                canonicalization_version="persistence-canonical-v1",
            ),
            correlation_id="synthetic-correlation",
            schema_version="audit-test-v1",
            software_version="test-build",
            created_at=AUDIT_TIME,
        )
        unit_of_work.commit()

    with Session(persistence_engine) as in_progress_session, pytest.raises(
        RuntimeError, match="already in progress"
    ), GovernedUnitOfWork(in_progress_session) as unit_of_work:
        service = RuleEvaluationService(unit_of_work)
        service.persist_evaluation(
            draft=RuleEvaluationPersistenceDraft(
                evaluation_id="in-progress-evaluation",
                revision_number=1,
                comparison=comparison,
                applicability_result=selected,
                observation=Observation("synthetic_parameter", 11.0, "synthetic_unit"),
                unit_context=UnitPolicyContext(expected_unit="synthetic_unit"),
            ),
            receipt_id="unused-in-progress-receipt",
            command_identity=CommandIdentity(
                command_namespace=RuleEvaluationService.COMMAND_NAMESPACE,
                command_scope="in-progress-evaluation",
                idempotency_key="in-progress-key",
            ),
            request_hash=CanonicalRequestHash(
                value=hashlib.sha256(b"pending-request").hexdigest(),
                hash_algorithm="sha256",
                canonicalization_version="persistence-canonical-v1",
            ),
            audit=_audit("idempotent-audit-in-progress"),
            completed_at=AUDIT_TIME,
        )


def test_success_audit_and_denial_audit_are_recorded(persistence_engine):
    with Session(persistence_engine) as session:
        _seed_rule(session)
        selected = _selected_resolution()
        requirement = RuleRequirement(
            rule_id=RULE_ID,
            revision=RULE_REVISION,
            parameter="synthetic_parameter",
            operator=RuleOperator.MIN,
            unit="synthetic_unit",
            min_value=10.0,
        )
        comparison = _comparison(
            requirement,
            Observation("synthetic_parameter", 11.0, "synthetic_unit"),
            applicability_result=selected,
            unit_context=UnitPolicyContext(expected_unit="synthetic_unit"),
        )
        persisted, receipt, audit_event = _persist(
            session,
            comparison=comparison,
            applicability_result=selected,
            observation=Observation("synthetic_parameter", 11.0, "synthetic_unit"),
            unit_context=UnitPolicyContext(expected_unit="synthetic_unit"),
            evaluation_id="audit-evaluation",
            receipt_id="audit-receipt",
            audit_event_id="audit-event-success",
        )
        assert audit_event.action == "PERSIST_RULE_EVALUATION"
        assert receipt.result_type == "rule_evaluation"
        assert persisted.revision_number == 1

        denial_resolution = GovernedApplicabilityResolution(
            outcome=ApplicabilityResolutionOutcome.CONFLICT,
            reason="synthetic conflict",
            decision_time=DECISION_TIME,
            context=selected.context,
            candidates=selected.candidates,
            conflict_candidate_ids=("other",),
        )
        denied_draft = RuleEvaluationPersistenceDraft(
            evaluation_id="audit-denial",
            revision_number=1,
            comparison=comparison,
            applicability_result=denial_resolution,
            observation=Observation("synthetic_parameter", 11.0, "synthetic_unit"),
            unit_context=UnitPolicyContext(expected_unit="synthetic_unit"),
        )
        session.rollback()
        with GovernedUnitOfWork(session) as unit_of_work:
            service = RuleEvaluationService(unit_of_work)
            denial_result = service.persist_evaluation(
                draft=denied_draft,
                receipt_id="audit-denial-receipt",
                command_identity=CommandIdentity(
                    command_namespace=RuleEvaluationService.COMMAND_NAMESPACE,
                    command_scope="audit-denial",
                    idempotency_key="denial-key",
                ),
                request_hash=CanonicalRequestHash(
                    value=hashlib.sha256(b"denial-request").hexdigest(),
                    hash_algorithm="sha256",
                    canonicalization_version="persistence-canonical-v1",
                ),
                audit=_audit("audit-event-denial", reason="Denial audit"),
                completed_at=AUDIT_TIME,
            )
            assert denial_result.result_type == "rule_evaluation_denial"
            unit_of_work.commit()

        denial_audit = GovernanceRepository(session).get_by_event_id("audit-event-denial")
        denial_receipt = session.scalar(
            select(GovernedCommandReceipt).where(
                GovernedCommandReceipt.command_scope == "audit-denial"
            )
        )
        assert denial_audit is not None
        assert denial_audit.action == "PERSIST_RULE_EVALUATION_DENIED"
        assert denial_receipt is not None
        assert denial_receipt.result_type == "rule_evaluation_denial"


def test_atomic_rollback_removes_all_writes_on_audit_failure(persistence_engine, monkeypatch):
    with Session(persistence_engine) as session:
        _seed_rule(session)
        selected = _selected_resolution()
        requirement = RuleRequirement(
            rule_id=RULE_ID,
            revision=RULE_REVISION,
            parameter="synthetic_parameter",
            operator=RuleOperator.MIN,
            unit="synthetic_unit",
            min_value=10.0,
        )
        comparison = _comparison(
            requirement,
            Observation("synthetic_parameter", 11.0, "synthetic_unit"),
            applicability_result=selected,
            unit_context=UnitPolicyContext(expected_unit="synthetic_unit"),
        )
        session.rollback()
        with GovernedUnitOfWork(session) as unit_of_work:
            service = RuleEvaluationService(unit_of_work)
            monkeypatch.setattr(
                service._audit,
                "record_event",
                lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    RuntimeError("audit failure")
                ),
            )
            with pytest.raises(RuntimeError, match="audit failure"):
                service.persist_evaluation(
                    draft=RuleEvaluationPersistenceDraft(
                        evaluation_id="rollback-evaluation",
                        revision_number=1,
                        comparison=comparison,
                        applicability_result=selected,
                        observation=Observation("synthetic_parameter", 11.0, "synthetic_unit"),
                        unit_context=UnitPolicyContext(expected_unit="synthetic_unit"),
                    ),
                    receipt_id="rollback-receipt",
                    command_identity=CommandIdentity(
                        command_namespace=RuleEvaluationService.COMMAND_NAMESPACE,
                        command_scope="rollback-evaluation",
                        idempotency_key="rollback-key",
                    ),
                    request_hash=CanonicalRequestHash(
                        value=hashlib.sha256(b"rollback-request").hexdigest(),
                        hash_algorithm="sha256",
                        canonicalization_version="persistence-canonical-v1",
                    ),
                    audit=_audit("rollback-audit"),
                    completed_at=AUDIT_TIME,
                )

        assert (
            session.scalar(
                select(RuleEvaluation).where(
                    RuleEvaluation.evaluation_id == "rollback-evaluation"
                )
            )
            is None
        )
        assert (
            session.scalar(
                select(GovernedCommandReceipt).where(
                    GovernedCommandReceipt.command_scope == "rollback-evaluation"
                )
            )
            is None
        )
        assert GovernanceRepository(session).get_by_event_id("rollback-audit") is None
