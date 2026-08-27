from __future__ import annotations

import ast
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

import pytest
from app.db.session import Base
from app.domain.governance_types import (
    ContentVersionMetadata,
    EvidenceClass,
    ImmutableRecordError,
    RegistryAuthorityError,
    RuleLifecycleStatus,
)
from app.domain.rule_registry_types import (
    EvidenceReferenceDraft,
    MissingHandling,
    RuleCategory,
    SafeDefault,
)
from app.models.governance import GovernedAuditEvent
from app.models.rule_registry import (
    EngineeringRuleRevision,
    EvidenceReference,
    RuleLifecycleEventType,
)
from app.repositories.rule_registry_repository import RuleRegistryRepository
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.orm import Session


@pytest.fixture()
def registry_session():
    registry_engine = create_engine("sqlite:///:memory:")

    @event.listens_for(registry_engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(registry_engine)
    with Session(registry_engine) as session:
        yield session
        session.rollback()
    with registry_engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        Base.metadata.drop_all(connection)
    registry_engine.dispose()


def _version_metadata(
    rule_id: str,
    revision: str,
    evidence_references: tuple[EvidenceReferenceDraft, ...] = (),
) -> ContentVersionMetadata:
    hash_payload = {
        "rule_id": rule_id,
        "revision": revision,
        "evidence": sorted(
            (reference.evidence_id, reference.evidence_revision)
            for reference in evidence_references
        ),
    }
    content_hash = hashlib.sha256(
        json.dumps(hash_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return ContentVersionMetadata(
        schema_version="registry-test-v1",
        canonicalization_version="test-canonical-v1",
        hash_algorithm="sha256",
        content_hash=content_hash,
        software_version="test-build",
    )


def _create_unresolved_revision(
    session: Session,
    *,
    rule_id: str = "TEST_UNRESOLVED_RULE",
    revision: str = "1.0",
    status: RuleLifecycleStatus = RuleLifecycleStatus.DRAFT,
    supersedes_revision_id: int | None = None,
    evidence_class: EvidenceClass = EvidenceClass.UNRESOLVED,
    enabled: bool = False,
    applicability_metadata: dict | None = None,
    evidence_references: tuple[EvidenceReferenceDraft, ...] = (),
):
    repository = RuleRegistryRepository(session)
    rule = repository.get_by_rule_id(rule_id)
    if rule is None:
        rule = repository.create_rule(
            rule_id=rule_id,
            created_by_actor_id="test-actor",
        )
    rule_revision = repository.create_revision(
        engineering_rule=rule,
        revision=revision,
        name="Synthetic unresolved requirement",
        status=status,
        evidence_class=evidence_class,
        category=RuleCategory.OTHER,
        parameter="synthetic_parameter",
        operator=None,
        min_value=None,
        max_value=None,
        unit=None,
        applicability_metadata=applicability_metadata,
        applicability_schema_version=None,
        effective_date=None,
        expiry_date=None,
        supersedes_revision_id=supersedes_revision_id,
        source_type=None,
        source_name=None,
        source_document=None,
        source_url=None,
        safe_default=SafeDefault.UNRESOLVED,
        missing_handling=MissingHandling.DATA_INSUFFICIENT,
        conflict_handling="REQUIRE_ENGINEERING_REVIEW",
        unit_mismatch_handling=None,
        description=None,
        note=None,
        enabled=enabled,
        reason_for_change="Synthetic persistence test",
        version_metadata=_version_metadata(rule_id, revision, evidence_references),
        created_by_actor_id="test-actor",
        evidence_references=evidence_references,
    )
    return repository, rule, rule_revision


def test_create_engineering_rule_identity_and_lookup(registry_session):
    repository = RuleRegistryRepository(registry_session)
    created = repository.create_rule(
        rule_id="TEST_RULE_IDENTITY",
        created_by_actor_id="test-actor",
    )

    created_id = created.id
    registry_session.commit()

    with Session(registry_session.get_bind()) as read_session:
        found = RuleRegistryRepository(read_session).get_by_rule_id("TEST_RULE_IDENTITY")

        assert found is not None
        assert found is not created
        assert found.id == created_id
        assert found.rule_id == "TEST_RULE_IDENTITY"


def test_create_two_revisions_preserves_first_and_orders_history(registry_session):
    _repository, _rule, first = _create_unresolved_revision(registry_session)
    registry_session.commit()
    first_id = first.id
    first_snapshot = {
        column.key: getattr(first, column.key)
        for column in EngineeringRuleRevision.__table__.columns
    }

    with Session(registry_session.get_bind()) as second_session:
        second_repository = RuleRegistryRepository(second_session)
        rule = second_repository.get_by_rule_id("TEST_UNRESOLVED_RULE")
        assert rule is not None
        second = second_repository.create_revision(
            engineering_rule=rule,
            revision="2.0",
            name="Synthetic unresolved requirement",
            status=RuleLifecycleStatus.DRAFT,
            evidence_class=EvidenceClass.UNRESOLVED,
            category=RuleCategory.OTHER,
            parameter="synthetic_parameter",
            safe_default=SafeDefault.UNRESOLVED,
            missing_handling=MissingHandling.DATA_INSUFFICIENT,
            enabled=False,
            reason_for_change="Synthetic persistence test",
            version_metadata=_version_metadata("TEST_UNRESOLVED_RULE", "2.0"),
            created_by_actor_id="test-actor",
            supersedes_revision_id=first_id,
        )
        second_session.commit()
        second_id = second.id

    with Session(registry_session.get_bind()) as read_session:
        repository = RuleRegistryRepository(read_session)
        history = repository.list_revisions("TEST_UNRESOLVED_RULE")

        assert [item.revision for item in history] == ["1.0", "2.0"]
        persisted_first = history[0]
        persisted_snapshot = {
            column.key: getattr(persisted_first, column.key)
            for column in EngineeringRuleRevision.__table__.columns
        }
        assert persisted_snapshot == first_snapshot
        assert history[1].id == second_id
        assert history[1].supersedes_revision_id == persisted_first.id
        assert repository.get_revision("TEST_UNRESOLVED_RULE", "2.0") is history[1]


def test_revision_listing_uses_creation_time_with_id_tiebreak(registry_session):
    _repository, _rule, first = _create_unresolved_revision(
        registry_session,
        rule_id="TEST_DETERMINISTIC_HISTORY",
        revision="1.0",
    )
    _repository, _rule, second = _create_unresolved_revision(
        registry_session,
        rule_id="TEST_DETERMINISTIC_HISTORY",
        revision="2.0",
        supersedes_revision_id=first.id,
    )
    _repository, _rule, third = _create_unresolved_revision(
        registry_session,
        rule_id="TEST_DETERMINISTIC_HISTORY",
        revision="3.0",
        supersedes_revision_id=second.id,
    )
    first_id = first.id
    second_id = second.id
    third_id = third.id
    registry_session.commit()

    with registry_session.get_bind().begin() as connection:
        connection.execute(
            EngineeringRuleRevision.__table__.update()
            .where(EngineeringRuleRevision.id == first_id)
            .values(created_at=datetime(2030, 1, 1, tzinfo=timezone.utc))
        )
        connection.execute(
            EngineeringRuleRevision.__table__.update()
            .where(EngineeringRuleRevision.id == second_id)
            .values(created_at=datetime(2029, 1, 1, tzinfo=timezone.utc))
        )
        connection.execute(
            EngineeringRuleRevision.__table__.update()
            .where(EngineeringRuleRevision.id == third_id)
            .values(created_at=datetime(2029, 1, 1, tzinfo=timezone.utc))
        )
    registry_session.expire_all()

    history = RuleRegistryRepository(registry_session).list_revisions(
        "TEST_DETERMINISTIC_HISTORY"
    )

    assert [item.id for item in history] == [second_id, third_id, first_id]


def test_rule_business_identifier_is_unique(registry_session):
    repository = RuleRegistryRepository(registry_session)
    repository.create_rule(rule_id="TEST_DUPLICATE_RULE", created_by_actor_id="actor-one")

    with pytest.raises(IntegrityError):
        repository.create_rule(
            rule_id="TEST_DUPLICATE_RULE",
            created_by_actor_id="actor-two",
        )


def test_actor_user_reference_rejects_unknown_user(registry_session):
    repository = RuleRegistryRepository(registry_session)

    with pytest.raises(IntegrityError):
        repository.create_rule(
            rule_id="TEST_UNKNOWN_ACTOR_USER",
            created_by_actor_id="missing-user-snapshot",
            created_by_user_id=999999,
        )


def test_revision_identifier_is_unique_within_rule(registry_session):
    _create_unresolved_revision(registry_session, rule_id="TEST_DUPLICATE_REVISION")

    with pytest.raises(IntegrityError):
        _create_unresolved_revision(registry_session, rule_id="TEST_DUPLICATE_REVISION")


def test_unresolved_revision_accepts_null_engineering_values(registry_session):
    _repository, _rule, revision = _create_unresolved_revision(registry_session)

    assert revision.evidence_class is EvidenceClass.UNRESOLVED
    assert revision.operator is None
    assert revision.min_value is None
    assert revision.max_value is None
    assert revision.unit is None
    assert revision.applicability_metadata is None
    assert revision.source_type is None


def test_evidence_classification_is_persisted_without_authority_claim(registry_session):
    evidence = EvidenceReferenceDraft(
        evidence_id="TEST_UNRESOLVED_EVIDENCE",
        evidence_revision="draft",
        evidence_class=EvidenceClass.UNRESOLVED,
        lifecycle_status=RuleLifecycleStatus.DRAFT,
        created_by_actor_id="test-actor",
        reference_metadata={"location": {"state": "unresolved"}},
    )
    _repository, _rule, revision = _create_unresolved_revision(
        registry_session,
        evidence_references=(evidence,),
    )
    registry_session.commit()
    registry_session.expire_all()

    persisted = revision.evidence_references[0]

    assert persisted is not None
    assert persisted.evidence_class is EvidenceClass.UNRESOLVED
    assert persisted.lifecycle_status is RuleLifecycleStatus.DRAFT
    assert persisted.source_type is None
    assert persisted.verified_at is None
    assert persisted.approved_at is None
    assert persisted.reference_metadata == {"location": {"state": "unresolved"}}

    with pytest.raises(TypeError, match="immutable"):
        persisted.reference_metadata["location"]["state"] = "changed"


def test_active_lifecycle_does_not_promote_unresolved_evidence(registry_session):
    _repository, _rule, revision = _create_unresolved_revision(
        registry_session,
        rule_id="TEST_ORTHOGONAL_STATES",
        status=RuleLifecycleStatus.ACTIVE,
    )

    assert revision.status is RuleLifecycleStatus.ACTIVE
    assert revision.evidence_class is EvidenceClass.UNRESOLVED
    assert revision.enabled is False


@pytest.mark.parametrize(
    ("evidence_class", "enabled"),
    [
        (EvidenceClass.SOURCE_BACKED, False),
        (EvidenceClass.UNRESOLVED, True),
    ],
)
def test_repository_rejects_authority_bearing_revision_creation(
    registry_session,
    evidence_class,
    enabled,
):
    with pytest.raises(RegistryAuthorityError):
        _create_unresolved_revision(
            registry_session,
            rule_id="TEST_REJECTED_AUTHORITY",
            evidence_class=evidence_class,
            enabled=enabled,
        )


def test_repository_allows_explicit_source_backed_revision_creation(
    registry_session,
):
    evidence = EvidenceReferenceDraft(
        evidence_id="TEST_SOURCE_BACKED_EVIDENCE",
        evidence_revision="1",
        evidence_class=EvidenceClass.UNRESOLVED,
        lifecycle_status=RuleLifecycleStatus.DRAFT,
        created_by_actor_id="test-actor",
        reference_uri="urn:test:source-backed",
    )
    repository = RuleRegistryRepository(registry_session)
    rule = repository.create_rule(
        rule_id="TEST_SOURCE_BACKED_RULE",
        created_by_actor_id="test-actor",
    )
    source_revision = repository.create_revision(
        engineering_rule=rule,
        revision="1.0",
        name="Synthetic source-backed source draft",
        status=RuleLifecycleStatus.DRAFT,
        evidence_class=EvidenceClass.UNRESOLVED,
        category=RuleCategory.OTHER,
        parameter="synthetic_parameter",
        operator=None,
        min_value=None,
        max_value=None,
        unit=None,
        applicability_metadata=None,
        applicability_schema_version=None,
        effective_date=None,
        expiry_date=None,
        supersedes_revision_id=None,
        source_type=None,
        source_name=None,
        source_document=None,
        source_url=None,
        safe_default=SafeDefault.UNRESOLVED,
        missing_handling=MissingHandling.DATA_INSUFFICIENT,
        conflict_handling="REQUIRE_ENGINEERING_REVIEW",
        unit_mismatch_handling=None,
        description=None,
        note=None,
        enabled=False,
        reason_for_change="Synthetic source-backed promotion source",
        version_metadata=_version_metadata(rule.rule_id, "1.0", (evidence,)),
        created_by_actor_id="test-actor",
        evidence_references=(evidence,),
    )

    promoted = repository.create_revision(
        engineering_rule=rule,
        revision="2.0",
        name="Synthetic source-backed revision",
        status=RuleLifecycleStatus.DRAFT,
        evidence_class=EvidenceClass.SOURCE_BACKED,
        category=source_revision.category,
        parameter=source_revision.parameter,
        operator=source_revision.operator,
        min_value=source_revision.min_value,
        max_value=source_revision.max_value,
        unit=source_revision.unit,
        applicability_metadata=source_revision.applicability_metadata,
        applicability_schema_version=source_revision.applicability_schema_version,
        effective_date=source_revision.effective_date,
        expiry_date=source_revision.expiry_date,
        supersedes_revision_id=source_revision.id,
        source_type=source_revision.source_type,
        source_name=source_revision.source_name,
        source_document=source_revision.source_document,
        source_url=source_revision.source_url,
        safe_default=source_revision.safe_default,
        missing_handling=source_revision.missing_handling,
        conflict_handling=source_revision.conflict_handling,
        unit_mismatch_handling=source_revision.unit_mismatch_handling,
        description=source_revision.description,
        note=source_revision.note,
        enabled=False,
        reason_for_change="Synthetic source-backed promotion",
        version_metadata=_version_metadata(rule.rule_id, "2.0", (evidence,)),
        created_by_actor_id="test-actor",
        evidence_references=source_revision.evidence_references,
        allow_source_backed=True,
    )
    registry_session.commit()
    registry_session.expire_all()

    persisted = repository.get_revision("TEST_SOURCE_BACKED_RULE", "2.0")
    assert promoted.evidence_class is EvidenceClass.SOURCE_BACKED
    assert persisted is not None
    assert persisted.evidence_class is EvidenceClass.SOURCE_BACKED
    assert persisted.supersedes_revision_id == source_revision.id
    assert len(persisted.evidence_references) == 1
    assert persisted.evidence_references[0].evidence_id == "TEST_SOURCE_BACKED_EVIDENCE"


def test_repository_records_rule_lifecycle_events_with_exact_scope_and_history(
    registry_session,
):
    repository = RuleRegistryRepository(registry_session)
    rule = repository.create_rule(
        rule_id="TEST_RULE_LIFECYCLE",
        created_by_actor_id="test-actor",
    )
    source_revision = repository.create_revision(
        engineering_rule=rule,
        revision="1.0",
        name="Synthetic lifecycle source-backed revision",
        status=RuleLifecycleStatus.DRAFT,
        evidence_class=EvidenceClass.SOURCE_BACKED,
        category=RuleCategory.OTHER,
        parameter="synthetic_parameter",
        operator=None,
        min_value=None,
        max_value=None,
        unit=None,
        applicability_metadata=None,
        applicability_schema_version=None,
        effective_date=None,
        expiry_date=None,
        supersedes_revision_id=None,
        source_type=None,
        source_name=None,
        source_document=None,
        source_url=None,
        safe_default=SafeDefault.UNRESOLVED,
        missing_handling=MissingHandling.DATA_INSUFFICIENT,
        conflict_handling="REQUIRE_ENGINEERING_REVIEW",
        unit_mismatch_handling=None,
        description=None,
        note=None,
        enabled=False,
        reason_for_change="Synthetic lifecycle source-backed revision",
        version_metadata=_version_metadata(rule.rule_id, "1.0"),
        created_by_actor_id="test-actor",
        allow_source_backed=True,
    )
    scope_snapshot = {"project": "synthetic-project"}
    basis_snapshot = {
        "rule_id": rule.rule_id,
        "source_revision_id": source_revision.id,
        "source_revision": source_revision.revision,
        "source_content_hash": source_revision.content_hash,
        "scope_snapshot": scope_snapshot,
        "evidence_pins": [],
        "content_hash": "basis-hash-1",
    }
    authority_snapshot = {
        "actor_id": "lifecycle-actor",
        "actor_user_id": 7,
        "actor_role": "Approver",
        "actor_type": "user",
        "lifecycle_capability": "ENABLE",
        "scope_snapshot": scope_snapshot,
        "effective_from": datetime(2031, 2, 3, 4, 5, 6, tzinfo=timezone.utc).isoformat(),
        "expires_at": None,
        "decision_at": datetime(2031, 2, 3, 4, 5, 6, tzinfo=timezone.utc).isoformat(),
        "correlation_id": "lifecycle-correlation",
        "policy_identifier": "SDS-115",
        "policy_version": "0.1 Draft",
    }

    enablement = repository.create_lifecycle_event(
        engineering_rule=rule,
        engineering_rule_revision=source_revision,
        lifecycle_event_id="TEST_RULE_LIFECYCLE:1.0:ENABLE:scope",
        revision_number=1,
        event_type=RuleLifecycleEventType.ENABLE,
        scope_snapshot=scope_snapshot,
        basis_snapshot=basis_snapshot,
        authority_snapshot=authority_snapshot,
        effective_from=datetime(2031, 2, 3, 4, 5, 6, tzinfo=timezone.utc),
        expires_at=None,
        created_by_actor_id="lifecycle-actor",
        created_by_user_id=None,
        schema_version="rule-lifecycle-v1",
        canonicalization_version="rule-lifecycle-canonical-v1",
        hash_algorithm="sha256",
        content_hash="lifecycle-hash-1",
        software_version="test-build",
        correlation_id="lifecycle-correlation",
    )
    correction = repository.create_lifecycle_event(
        engineering_rule=rule,
        engineering_rule_revision=source_revision,
        lifecycle_event_id="TEST_RULE_LIFECYCLE:1.0:ENABLE:scope",
        revision_number=2,
        event_type=RuleLifecycleEventType.CORRECT,
        scope_snapshot=scope_snapshot,
        basis_snapshot={**basis_snapshot, "content_hash": "basis-hash-2"},
        authority_snapshot={**authority_snapshot, "lifecycle_capability": "CORRECT"},
        effective_from=datetime(2031, 2, 3, 4, 5, 7, tzinfo=timezone.utc),
        expires_at=None,
        created_by_actor_id="lifecycle-actor",
        created_by_user_id=None,
        schema_version="rule-lifecycle-v1",
        canonicalization_version="rule-lifecycle-canonical-v1",
        hash_algorithm="sha256",
        content_hash="lifecycle-hash-2",
        software_version="test-build",
        correlation_id="lifecycle-correlation",
        supersedes_rule_lifecycle_event_id=enablement.id,
    )
    registry_session.commit()
    registry_session.expire_all()

    latest = repository.get_latest_lifecycle_event(
        engineering_rule_revision_id=source_revision.id,
        scope_snapshot=scope_snapshot,
        event_types=(RuleLifecycleEventType.ENABLE, RuleLifecycleEventType.CORRECT),
    )
    assert latest is not None
    assert latest.id == correction.id
    assert latest.scope_snapshot == scope_snapshot
    assert latest.basis_snapshot["content_hash"] == "basis-hash-2"
    assert repository.get_latest_lifecycle_event(
        engineering_rule_revision_id=source_revision.id,
        scope_snapshot={"project": "other"},
        event_types=(RuleLifecycleEventType.ENABLE, RuleLifecycleEventType.CORRECT),
    ) is None
    history = repository.list_lifecycle_history(
        "TEST_RULE_LIFECYCLE:1.0:ENABLE:scope"
    )
    assert [event.revision_number for event in history] == [1, 2]
    assert history[0].event_type is RuleLifecycleEventType.ENABLE
    assert history[1].event_type is RuleLifecycleEventType.CORRECT


@pytest.mark.parametrize(
    ("evidence_class", "lifecycle_status"),
    [
        (EvidenceClass.SOURCE_BACKED, RuleLifecycleStatus.DRAFT),
        (EvidenceClass.UNRESOLVED, RuleLifecycleStatus.ACTIVE),
    ],
)
def test_repository_accepts_only_unverified_evidence_drafts(
    registry_session,
    evidence_class,
    lifecycle_status,
):
    evidence = EvidenceReferenceDraft(
        evidence_id="TEST_REJECTED_EVIDENCE",
        evidence_revision="draft",
        evidence_class=evidence_class,
        lifecycle_status=lifecycle_status,
        created_by_actor_id="test-actor",
    )

    with pytest.raises(RegistryAuthorityError):
        _create_unresolved_revision(
            registry_session,
            rule_id="TEST_REJECTED_EVIDENCE_RULE",
            evidence_references=(evidence,),
        )

    rejected_rule = RuleRegistryRepository(registry_session).get_by_rule_id(
        "TEST_REJECTED_EVIDENCE_RULE"
    )
    assert rejected_rule is not None
    assert registry_session.scalar(
        select(EngineeringRuleRevision).where(
            EngineeringRuleRevision.engineering_rule_id == rejected_rule.id
        )
    ) is None


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("status", "UNKNOWN_LIFECYCLE"),
        ("evidence_class", "UNKNOWN_EVIDENCE"),
    ],
)
def test_unknown_governance_enums_are_rejected(
    registry_session,
    field: str,
    invalid_value: str,
):
    repository = RuleRegistryRepository(registry_session)
    rule = repository.create_rule(
        rule_id=f"TEST_INVALID_{field.upper()}",
        created_by_actor_id="test-actor",
    )
    values: dict[str, Any] = {
        "engineering_rule": rule,
        "revision": "1.0",
        "name": "Synthetic invalid enum record",
        "status": RuleLifecycleStatus.DRAFT,
        "evidence_class": EvidenceClass.UNRESOLVED,
        "category": RuleCategory.OTHER,
        "parameter": "synthetic_parameter",
        "safe_default": SafeDefault.UNRESOLVED,
        "missing_handling": MissingHandling.DATA_INSUFFICIENT,
        "enabled": False,
        "reason_for_change": "Negative persistence test",
        "version_metadata": _version_metadata(rule.rule_id, "1.0"),
        "created_by_actor_id": "test-actor",
    }
    values[field] = invalid_value

    with pytest.raises(StatementError):
        repository.create_revision(**cast(Any, values))


def test_repository_does_not_commit_caller_transaction(registry_session):
    repository = RuleRegistryRepository(registry_session)
    repository.create_rule(
        rule_id="TEST_CALLER_TRANSACTION",
        created_by_actor_id="test-actor",
    )

    registry_session.rollback()

    assert repository.get_by_rule_id("TEST_CALLER_TRANSACTION") is None


def test_revision_update_and_delete_are_rejected(registry_session):
    repository, _rule, revision = _create_unresolved_revision(registry_session)
    revision_id = revision.id
    original_hash = revision.content_hash
    registry_session.commit()

    revision.content_hash = "changed-content-hash"
    with pytest.raises(ImmutableRecordError):
        registry_session.flush()
    registry_session.rollback()

    persisted = registry_session.get(EngineeringRuleRevision, revision_id)
    assert persisted is not None
    assert persisted.content_hash == original_hash

    registry_session.delete(persisted)
    with pytest.raises(ImmutableRecordError):
        registry_session.flush()
    registry_session.rollback()

    assert repository.get_revision("TEST_UNRESOLVED_RULE", "1.0") is not None


def test_revision_nested_json_snapshot_is_immutable(registry_session):
    _repository, _rule, revision = _create_unresolved_revision(
        registry_session,
        rule_id="TEST_IMMUTABLE_JSON",
        applicability_metadata={"context": {"labels": ["synthetic"]}},
    )
    registry_session.commit()

    with pytest.raises(TypeError, match="immutable"):
        revision.applicability_metadata["context"]["labels"] = ["changed"]
    with pytest.raises(TypeError, match="immutable"):
        revision.applicability_metadata["new_key"] = "changed"


def test_evidence_reference_update_and_delete_are_rejected(registry_session):
    evidence = EvidenceReferenceDraft(
        evidence_id="TEST_IMMUTABLE_EVIDENCE",
        evidence_revision="draft",
        evidence_class=EvidenceClass.UNRESOLVED,
        lifecycle_status=RuleLifecycleStatus.DRAFT,
        created_by_actor_id="test-actor",
    )
    _repository, _rule, revision = _create_unresolved_revision(
        registry_session,
        rule_id="TEST_EVIDENCE_IMMUTABILITY",
        evidence_references=(evidence,),
    )
    registry_session.commit()
    reference_id = revision.evidence_references[0].id

    revision.evidence_references[0].source_name = "changed source"
    with pytest.raises(ImmutableRecordError):
        registry_session.flush()
    registry_session.rollback()

    persisted = registry_session.get(EvidenceReference, reference_id)
    assert persisted is not None
    assert persisted.source_name is None
    registry_session.delete(persisted)
    with pytest.raises(ImmutableRecordError):
        registry_session.flush()
    registry_session.rollback()


def test_late_evidence_collection_append_cannot_persist(registry_session):
    _repository, _rule, revision = _create_unresolved_revision(
        registry_session,
        rule_id="TEST_LATE_EVIDENCE",
    )
    registry_session.commit()
    revision_id = revision.id
    late_reference = EvidenceReference(
        engineering_rule_revision_id=revision_id,
        evidence_id="TEST_LATE_EVIDENCE_REFERENCE",
        evidence_revision="draft",
        evidence_class=EvidenceClass.UNRESOLVED,
        lifecycle_status=RuleLifecycleStatus.DRAFT,
        created_by_actor_id="test-actor",
    )

    revision.evidence_references.append(late_reference)
    registry_session.flush()
    assert late_reference not in registry_session
    registry_session.expire(revision, ["evidence_references"])
    assert revision.evidence_references == []

    registry_session.add(late_reference)
    late_reference._phase1_revision_assembly = True
    with pytest.raises(RegistryAuthorityError, match="assembled with a new revision"):
        registry_session.flush()
    registry_session.rollback()


def test_cross_rule_supersession_is_rejected(registry_session):
    _repository, _first_rule, first_revision = _create_unresolved_revision(
        registry_session,
        rule_id="TEST_FIRST_RULE",
    )
    repository = RuleRegistryRepository(registry_session)
    second_rule = repository.create_rule(
        rule_id="TEST_SECOND_RULE",
        created_by_actor_id="test-actor",
    )

    with pytest.raises(ValueError, match="same rule"):
        repository.create_revision(
            engineering_rule=second_rule,
            revision="1.0",
            name="Synthetic cross-rule supersession",
            status=RuleLifecycleStatus.DRAFT,
            evidence_class=EvidenceClass.UNRESOLVED,
            category=RuleCategory.OTHER,
            parameter="synthetic_parameter",
            safe_default=SafeDefault.UNRESOLVED,
            missing_handling=MissingHandling.DATA_INSUFFICIENT,
            enabled=False,
            reason_for_change="Negative persistence test",
            version_metadata=_version_metadata(second_rule.rule_id, "1.0"),
            created_by_actor_id="test-actor",
            supersedes_revision_id=first_revision.id,
        )


def _audit_event() -> GovernedAuditEvent:
    return GovernedAuditEvent(
        event_id="test-audit-event",
        entity_type="engineering_rule_revision",
        entity_id="TEST_UNRESOLVED_RULE",
        entity_revision="1.0",
        action="CREATE_REVISION",
        actor_id="test-actor",
        actor_type="user",
        actor_role="test-role",
        authority_scope=None,
        reason="Synthetic persistence test",
        correlation_id="test-correlation",
        idempotency_key=None,
        schema_version="audit-test-v1",
        software_version="test-build",
        canonicalization_version="test-canonical-v1",
        hash_algorithm="sha256",
        prior_content_hash=None,
        new_content_hash="a" * 64,
        detail=None,
    )


def test_governed_audit_event_is_append_only(registry_session):
    event_record = _audit_event()
    registry_session.add(event_record)
    registry_session.commit()
    event_id = event_record.id

    event_record.action = "CHANGED_ACTION"
    with pytest.raises(ImmutableRecordError):
        registry_session.flush()
    registry_session.rollback()

    persisted = registry_session.get(GovernedAuditEvent, event_id)
    assert persisted is not None
    assert persisted.action == "CREATE_REVISION"
    registry_session.delete(persisted)
    with pytest.raises(ImmutableRecordError):
        registry_session.flush()
    registry_session.rollback()


def test_governed_audit_event_requires_correlation_metadata(registry_session):
    event_record = _audit_event()
    event_record.event_id = "test-audit-event-missing-correlation"
    event_record.correlation_id = None  # type: ignore[assignment]
    registry_session.add(event_record)

    with pytest.raises(IntegrityError):
        registry_session.flush()


def test_registry_foundation_does_not_import_prototype_modules():
    backend_root = Path(__file__).parents[1]
    registry_files = [
        backend_root / "app" / "domain" / "governance_types.py",
        backend_root / "app" / "domain" / "rule_registry_types.py",
        backend_root / "app" / "models" / "governance.py",
        backend_root / "app" / "models" / "rule_registry.py",
        backend_root / "app" / "repositories" / "rule_registry_repository.py",
        backend_root / "app" / "models" / "__init__.py",
        backend_root / "alembic" / "versions" / "0003_registry_foundation.py",
    ]
    prohibited_modules = {
        "app.domain.rules_engine",
        "app.domain.engine",
        "app.domain.materials",
        "app.domain.models",
        "app.domain.model_registry",
        "app.domain.doe_optimizer",
        "app.domain.ensemble",
        "app.domain.polynomial_model",
        "app.domain.model_validation",
        "app.domain.electrode_life",
        "app.domain.weld_lobe",
        "app.domain.pulse_strategy",
        "app.domain.dynamic_resistance",
        "app.domain.sensitivity",
        "app.domain.energy",
        "app.domain.failure_probability",
        "app.application.engineering_service",
        "app.application.failure_probability_service",
        "app.application.optimization_service",
        "app.application.weld_analysis_service",
        "app.api.v1.engineering",
        "app.api.v1.failure_probability",
        "app.api.v1.optimization",
        "app.api.v1.weld_analysis",
    }

    imported_modules: set[str] = set()
    source_texts: list[str] = []
    for path in registry_files:
        source = path.read_text(encoding="utf-8")
        source_texts.append(source)
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.add(node.module)

    assert imported_modules.isdisjoint(prohibited_modules)
    assert not any(
        module.startswith(f"{prohibited}.")
        for module in imported_modules
        for prohibited in prohibited_modules
    )
    assert "model4_full.json" not in "\n".join(source_texts)
