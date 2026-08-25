from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import Base
from app.domain.governance_types import (
    ContentVersionMetadata,
    EvidenceClass,
    ImmutableRecordError,
    RuleLifecycleStatus,
)
from app.domain.rule_registry_types import (
    ApplicabilityDimension,
    MissingHandling,
    RuleCategory,
    SafeDefault,
)
from app.models.rule_registry import RuleApplicability
from app.repositories.rule_registry_repository import RuleRegistryRepository


@pytest.fixture()
def applicability_engine():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


def _revision(session: Session, rule_id: str, revision: str = "draft-1"):
    repository = RuleRegistryRepository(session)
    rule = repository.get_by_rule_id(rule_id)
    if rule is None:
        rule = repository.create_rule(rule_id=rule_id, created_by_actor_id="actor")
    result = repository.create_revision(
        engineering_rule=rule,
        revision=revision,
        name="Synthetic applicability holder",
        status=RuleLifecycleStatus.DRAFT,
        evidence_class=EvidenceClass.UNRESOLVED,
        category=RuleCategory.OTHER,
        parameter="synthetic_parameter",
        safe_default=SafeDefault.UNRESOLVED,
        missing_handling=MissingHandling.DATA_INSUFFICIENT,
        enabled=False,
        reason_for_change="Synthetic persistence test",
        version_metadata=ContentVersionMetadata(
            schema_version="test-v1",
            canonicalization_version="canonical-v1",
            hash_algorithm="sha256",
            content_hash=f"{rule_id}-{revision}",
            software_version="test-build",
        ),
        created_by_actor_id="actor",
    )
    return rule, result


def _applicability(rule, revision, *, number=1, prior_id=None):
    return RuleApplicability(
        engineering_rule_id=rule.id,
        engineering_rule_revision_id=revision.id,
        applicability_id="SYNTHETIC_MATERIAL_SCOPE",
        applicability_revision=number,
        supersedes_applicability_id=prior_id,
        dimension=ApplicabilityDimension.MATERIAL_FAMILY,
        allowed_values={"values": ["synthetic-material"]},
        policy_version="categorical-membership-v1",
        schema_version="applicability-test-v1",
        created_by_actor_id="actor",
    )


def test_applicability_persists_typed_immutable_definition(applicability_engine):
    with Session(applicability_engine) as session:
        rule, revision = _revision(session, "APPLICABILITY_RULE")
        applicability = _applicability(rule, revision)
        session.add(applicability)
        session.commit()
        applicability_id = applicability.id
    with Session(applicability_engine) as read_session:
        persisted = read_session.get(RuleApplicability, applicability_id)
        assert persisted.dimension is ApplicabilityDimension.MATERIAL_FAMILY
        assert persisted.allowed_values == {"values": ("synthetic-material",)}
        with pytest.raises(TypeError, match="immutable"):
            persisted.allowed_values["values"] = ["changed"]
        persisted.policy_version = "changed"
        with pytest.raises(ImmutableRecordError):
            read_session.flush()


def test_applicability_revision_identity_and_single_successor_are_enforced(
    applicability_engine,
):
    with Session(applicability_engine) as session:
        rule, first_rule_revision = _revision(session, "VERSIONED_SCOPE", "draft-1")
        first = _applicability(rule, first_rule_revision)
        session.add(first)
        session.flush()
        _rule, second_rule_revision = _revision(session, "VERSIONED_SCOPE", "draft-2")
        second = _applicability(rule, second_rule_revision, number=2, prior_id=first.id)
        session.add(second)
        session.commit()
        first_id = first.id
    with Session(applicability_engine) as duplicate:
        rule = RuleRegistryRepository(duplicate).get_by_rule_id("VERSIONED_SCOPE")
        revision = RuleRegistryRepository(duplicate).get_revision("VERSIONED_SCOPE", "draft-2")
        duplicate.add(_applicability(rule, revision, number=2, prior_id=first_id))
        with pytest.raises(IntegrityError):
            duplicate.flush()


def test_applicability_cannot_reference_revision_from_another_rule(
    applicability_engine,
):
    with Session(applicability_engine) as session:
        first_rule, _first_revision = _revision(session, "FIRST_SCOPE_RULE")
        _second_rule, second_revision = _revision(session, "SECOND_SCOPE_RULE")
        session.flush()
        invalid = _applicability(first_rule, second_revision)
        session.add(invalid)
        with pytest.raises(IntegrityError):
            session.flush()


def test_applicability_supersession_cannot_cross_logical_rule(
    applicability_engine,
):
    with Session(applicability_engine) as session:
        first_rule, first_revision = _revision(session, "FIRST_LOGICAL_RULE")
        first = _applicability(first_rule, first_revision)
        session.add(first)
        session.flush()
        second_rule, second_revision = _revision(session, "SECOND_LOGICAL_RULE")
        invalid = _applicability(second_rule, second_revision, number=2, prior_id=first.id)
        session.add(invalid)
        with pytest.raises(IntegrityError):
            session.flush()


def test_applicability_delete_and_nonpositive_revision_are_rejected(
    applicability_engine,
):
    with Session(applicability_engine) as session:
        rule, revision = _revision(session, "IMMUTABLE_SCOPE")
        applicability = _applicability(rule, revision)
        session.add(applicability)
        session.commit()
        session.delete(applicability)
        with pytest.raises(ImmutableRecordError):
            session.flush()
        session.rollback()
        invalid = _applicability(rule, revision, number=0)
        invalid.applicability_id = "INVALID_SCOPE"
        session.add(invalid)
        with pytest.raises(IntegrityError):
            session.flush()


def test_r2_production_files_contain_no_evaluator_or_engineering_thresholds():
    backend_root = Path(__file__).parents[1]
    paths = [
        backend_root / "app" / "models" / "rule_registry.py",
        backend_root / "app" / "repositories" / "rule_evidence_repository.py",
        backend_root / "app" / "application" / "rule_evidence_service.py",
        backend_root / "alembic" / "versions" / "0005_registry_evidence_applicability.py",
    ]
    source = "\n".join(path.read_text(encoding="utf-8") for path in paths).lower()
    assert "rules_engine" not in source
    assert "default_rules" not in source
    assert "evaluate_applicability" not in source
    assert "rule_evaluations" not in source
    assert "verify_evidence" not in source
    assert "approve_evidence" not in source
    assert "promote_source_backed" not in source
    assert "enable_rule" not in source
    assert "activate_revision" not in source
