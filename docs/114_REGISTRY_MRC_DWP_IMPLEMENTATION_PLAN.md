# 114 — Registry + MRC + DWP Implementation Architecture Plan

**Document ID:** SDS-114  
**Status:** Implementation planning only — no production implementation authorized by this document  
**Repository:** `D:\SpotWeld-AI`  
**Authoritative SDS index:** [`../100_SDS_MASTER_INDEX.md`](../100_SDS_MASTER_INDEX.md)  
**Approved semantic baseline:** [`111_ENGINEERING_RULE_REGISTRY_DESIGN.md`](111_ENGINEERING_RULE_REGISTRY_DESIGN.md), [`112_MACHINE_READINESS_CHECK_DESIGN.md`](112_MACHINE_READINESS_CHECK_DESIGN.md), [`113_DIGITAL_WELD_PASSPORT_DESIGN.md`](113_DIGITAL_WELD_PASSPORT_DESIGN.md)  
**Scope:** Safe implementation sequencing, persistence planning, service/API boundaries, authorization, audit, tests, and release gates  
**Out of scope:** Production code, migrations, frontend/backend changes, engineering-threshold selection, evidence promotion, deployment, staging, commit, and release

## 0. Executive decision and planning boundary

Documents 111–113 define the semantic baseline for this plan. This document translates that baseline into repository-specific implementation work; it does not revise the approved subsystem ownership, safety states, evidence classifications, or the 16-item MRC unresolved inventory.

The current repository can support threshold-free implementation foundations. It cannot yet support governed engineering decisions or production release because:

- no persistent Engineering Rule Registry, MRC, or DWP subsystem exists;
- current rule and engineering constants are implementation prototypes, not authoritative engineering evidence;
- the MRC inventory remains exactly 16 `UNRESOLVED` items, with zero current `SOURCE_BACKED` MRC items;
- current audit writes are not atomic with all governed writes;
- current permissions are too coarse for engineering review, MRC review, DWP approval, and release separation;
- current project, weld-point, approval, test-result, and revision records do not provide the immutability and complete lineage required by documents 111–113.

Repository metadata still labels the source designs as design-only/draft or awaiting review. The task identifies them as the approved semantic baseline; therefore Phase 0 must record the responsible human architecture/security/data-owner sign-offs and freeze this baseline before coding starts. This is a delivery gate, not a reason to change the semantics here.

**Plan conclusion:** implementation planning is GO. Threshold-free architecture may begin after Phase 0. Engineering enablement and production release remain NO-GO until their separate gates pass.

## 1. Current repository baseline

### 1.1 Package and runtime structure

The repository follows the root SDS layered direction:

```text
frontend/                         React + TypeScript presentation
backend/app/api/v1/               FastAPI route adapters under /api/v1
backend/app/schemas/              Pydantic request/response contracts
backend/app/application/          application services and orchestration
backend/app/domain/               intended domain layer; currently also contains prototype/file-reading logic
backend/app/repositories/         present but currently empty
backend/app/models/               SQLAlchemy persistence models
backend/app/db/                   engine/session/Base
backend/alembic/                  Alembic environment and versioned migrations
backend/tests/                    pytest + FastAPI TestClient tests
.github/workflows/ci.yml          backend pytest and frontend build gates
```

Runtime persistence uses SQLAlchemy 2.x. `backend/app/db/session.py` selects PostgreSQL through `DATABASE_URL` and falls back to a local SQLite development database. Docker Compose provisions PostgreSQL 16 and applies `alembic upgrade head` before starting FastAPI. Alembic currently has two linear revisions:

1. `backend/alembic/versions/0001_initial.py` — projects, weld points, weld-point revisions, approvals.
2. `backend/alembic/versions/0002_auth_audit.py` — users, generic audit logs, test results.

The ORM metadata and migrations already show drift risk: several `index=True` declarations in `entities.py` (including weld-point, revision, approval, audit, and test-result lookup fields) are not consistently represented as explicit indexes in migrations 0001/0002. Because current tests use `Base.metadata.create_all`, they do not prove that an Alembic-created schema matches ORM metadata. Phase 0 and every future migration must include drift validation.

The test suite contains 17 discovered `test_*` functions. Tests use pytest, FastAPI `TestClient`, a disposable SQLite database, `Base.metadata.create_all`, and an authenticated System Admin fixture. CI runs those tests against SQLite and builds the frontend. No Registry, MRC, DWP, migration-integrity, PostgreSQL-specific, concurrency, idempotency, or governed-audit test exists.

Current API modules use function-based routers, FastAPI dependencies, Pydantic models, synchronous SQLAlchemy sessions, and `HTTPException`. Coverage is inconsistent: several responses are untyped dictionaries, list endpoints generally lack pagination, no versioned structured-error envelope/idempotency/ETag convention exists, and the current `/api/v1/weld-analysis` route has no authorization dependency. `ProjectService` performs direct SQLAlchemy work, commits inside individual methods, and raises HTTP-layer exceptions from the application layer; there is no common unit-of-work boundary.

The repository has no application logging/observability implementation beyond framework/runtime output and the generic database audit records. `docs/39_LOGGING.md` is a placeholder. Operational logs/metrics/traces remain distinct from the governed audit trail and require a later production-observability design; they must not replace atomic audit publication.

Current audit coverage is also partial: `write_audit()` is called for login, user creation, and test-result creation only. Project, weld-point, weld-point revision, approval, analysis, and engineering paths do not publish matching audit events. User/test-result domain data is committed before the separately committing audit call, so audit failure can occur after state has already changed.

### 1.2 Component classification

Classification meanings:

- `REUSE`: retain the existing component/pattern as a foundation.
- `EXTEND`: retain it but add governed behavior or fields.
- `REPLACE`: do not use the existing behavior for the governed path; introduce a compatible authoritative path while preserving legacy compatibility until separately deprecated.
- `QUARANTINE`: isolate prototype logic/data from Registry, MRC, DWP, approval, and release authority.
- `NEW`: no adequate current component exists.

| Component | Exact current path | Finding | Classification | Planned treatment |
|---|---|---|---|---|
| Layered package boundary | `backend/app/{api,schemas,application,domain,repositories,models,db}` | Structurally aligns with the SDS direction, but dependency hygiene is incomplete: `model_registry.py` reads files and current application services couple SQLAlchemy/FastAPI concerns; repository layer is empty | `REUSE` structure, `EXTEND` boundaries | Add new subsystem modules inside existing layers; new domain code remains free of FastAPI, SQLAlchemy, filesystem/environment, and deployment access |
| FastAPI application and version prefix | `backend/app/main.py`, `backend/app/api/v1/` | Routers are mounted under `/api/v1` | `REUSE` | Add routers only after domain, persistence, authorization, and failure contracts are tested |
| Pydantic contracts | `backend/app/schemas/` | Request/response models with validation and `from_attributes` are established | `REUSE` | Add explicit enum/reason/reference contracts; never infer engineering status from HTTP status |
| SQLAlchemy session/Base | `backend/app/db/session.py` | Session-per-request and PostgreSQL/SQLite support exist | `EXTEND` | Reuse session ownership; define explicit transaction ownership for governed writes and audit publication |
| Alembic | `backend/alembic/`, `backend/alembic.ini` | Linear versioned migrations are established | `REUSE` | Add small dependency-ordered migrations; require upgrade/downgrade and PostgreSQL validation before merge |
| Generic models file | `backend/app/models/entities.py` | Holds all current entities in one module | `EXTEND` | Keep legacy entities; add subsystem-specific model modules to avoid enlarging this file and export them through `models/__init__.py` |
| Project identity | `Project` in `backend/app/models/entities.py` | Useful project/customer/platform context; mutable and deletable | `EXTEND` | Reference stable ID and snapshot decision-critical values; add retention protection before any DWP production use |
| Weld-point identity | `WeldPoint` in `backend/app/models/entities.py` | Useful project/point/part/station/robot/gun/operation identity; current row is mutable | `EXTEND` | Reference identity but never treat the mutable row as an immutable DWP revision |
| Weld-point revision | `WeldPointRevision` | Captures prior JSON snapshot and reason | `REPLACE` for DWP authority | Preserve legacy revisions; DWP gets its own sealed immutable revision aggregate, hashes, exact references, and supersession chain |
| Approval | `Approval`, `ProjectService.add_approval` | Free-text approver and mutable `WeldPoint.approval_status` | `REPLACE` for governed decisions | Preserve legacy behavior; use durable user/role/authority references and revision-scoped append-only DWP/MRC review records |
| Test result | `TestResult`, `backend/app/api/v1/tests.py` | Generic test name/value/unit and caller-supplied acceptance status | `EXTEND` as evidence source; `REPLACE` for governed acceptance | Existing rows may be referenced as legacy evidence only; new quality evidence requires method, criterion/rule revision, provenance, correction, and attachment lineage |
| User/JWT identity | `User`, `backend/app/core/security.py`, `get_current_user`, `backend/app/schemas/auth.py` | Durable `User.id` exists, but access/refresh token `sub` is the email resolved on each request and `UserCreate.role` accepts an unconstrained string | `REUSE` authentication, `EXTEND` governed identity/authority | Do not create another authentication system; governed audit/decisions pin resolved `User.id` plus role/authority/scope snapshot, while Phase 0 decides token subject, service identity, rotation/revocation, and role validation policy |
| Role permission map | `backend/app/api/dependencies.py` | Coarse in-code permission sets; System Admin wildcard | `EXTEND` | Add granular Registry/MRC/DWP permissions, scope checks, delegated engineering authority, and separation-of-duties policy |
| Generic audit | `AuditLog`, `backend/app/application/audit_service.py`, `/api/v1/audit` | Generic JSON details; `write_audit` commits independently | `REPLACE` for governed publication | Retain legacy log; add transaction-participating governed events with revisions, hashes, reasons, correlation, software version, and before/after data |
| Application logging/observability | framework defaults; `docs/39_LOGGING.md` is a placeholder | No structured application logging, metrics, tracing, or correlation propagation contract | `NEW` production support, separate from audit | Add only after telemetry/security/retention policy; governed audit remains the authoritative state-change record |
| Application service layer/location | `backend/app/application/*_service.py` | Package, naming, and dependency-injection shape are useful, but `ProjectService` owns SQLAlchemy commits and raises FastAPI `HTTPException` | `EXTEND` | Reuse the layer/location while governed services use typed application/domain errors, injected repositories/policies, and a caller-owned atomic transaction |
| Repository abstraction | `backend/app/repositories/__init__.py` | Empty package | `NEW` implementation within existing layer | Add repository interfaces/adapters so domain/application logic does not depend on SQLAlchemy |
| Prototype rule dataclass/evaluator | `backend/app/domain/rules_engine.py` | Inline rules, no evidence/lifecycle/revisions, automatic priority winner, PASS/FAIL from prototypes | `QUARANTINE` and `REPLACE` for governed use | Keep legacy endpoints compatible; no Registry/MRC/DWP import may use `DEFAULT_RULES`, `_evaluate_rule`, `detect_conflicts`, or `evaluate_compliance` as authority |
| Weld analysis composition | `backend/app/application/weld_analysis_service.py` | Directly invokes prototype models and `evaluate_compliance` | `QUARANTINE` from governed path | Preserve current API behavior until a separate deprecation/integration change; never let its outputs release MRC/DWP |
| Engineering/model/risk prototypes | `backend/app/domain/engine.py`, `materials.py`, `models.py`, `model_registry.py`, `doe_optimizer.py`, `ensemble.py`, `polynomial_model.py`, `model_validation.py`, `electrode_life.py`, `weld_lobe.py`, `pulse_strategy.py`, `dynamic_resistance.py`, `sensitivity.py`, `energy.py`, `failure_probability.py` | Contain material-support labels, tables, formulas, coefficients, limits, rankings, validation/eligibility cutoffs, and advisory calculations without Registry evidence lineage | `QUARANTINE` | May remain legacy/advisory/test-compatible; DWP may reference explicitly versioned advisory results only after model governance exists; none is `SOURCE_BACKED` rule evidence |
| Existing frontend | `frontend/src/` | No Registry/MRC/DWP screens or state model | `EXTEND` later | Leave untouched until API/state/RBAC contracts stabilize; later add views that display server-owned states and never implement client-side readiness logic |
| CI | `.github/workflows/ci.yml` | Runs pytest on SQLite and frontend build | `EXTEND` | Later add migration checks, PostgreSQL integration, architecture/import checks, and governed negative-path tests |

### 1.3 Current domain entities and relevance

| Existing entity/concept | Useful data | Limitation for the new subsystems |
|---|---|---|
| `Project` | project code/name, customer, platform, status | mutable; cascade deletion conflicts with governed DWP retention |
| `WeldPoint` | project, point code, part/revision, station, robot, gun, operation, criticality, analysis | mutable aggregate; analysis JSON can contain prototype results; no stable sealed engineering record |
| `WeldPointRevision` | revision number, actor text, reason, JSON snapshot, time | snapshots only prior weld-point state; no content hash or rule/MRC/evidence/model/software lineage |
| `Approval` | type, approver text, status, note, time | no durable user FK, authority snapshot, exact revision scope, separation of duties, withdrawal/supersession chain, or atomic audit |
| `TestResult` | weld point, type, numeric value/unit, status, note, actor text/time | acceptance status is ungoverned; no method/criterion/evidence revision or immutable correction chain |
| `User` | durable user ID, email, name, role, active flag | one coarse role string; no delegated authority or project/customer/site scope model |
| `AuditLog` | actor ID, action, entity identity, JSON detail, time | no correlation/idempotency, software version, before/after hashes, revision scope, integrity chain, or atomic publication guarantee |
| `RegisteredModel` | in-memory model key/name/source priority/validation label/supported materials in `backend/app/domain/model_registry.py` | not persistent; no immutable artifact/dataset/evidence lifecycle or governed execution record |
| `ModelResult` | transient model name/prediction/confidence/status/note in `backend/app/domain/models.py` | not persistent and not tied to immutable model/dataset/input/software provenance; cannot establish governed truth |
| Analysis/model output | parameter, material/stack, selected model, compliance/risk outputs embedded in response or `WeldPoint.analysis_result` | prototype provenance and applicability are incomplete; no persistent model-result entity exists; current outputs cannot establish governed engineering truth |

No machine, gun, electrode, recipe, material-stack revision, calibration-device, evidence-document, validation-plan, actual-cycle, Registry, MRC, or DWP persistence entity exists. Those dependencies must either be represented as immutable external/versioned references plus snapshots, or introduced through separately owned master-data work. Document 114 does not invent those master systems.

### 1.4 Prototype/default rule family inventory

This inventory identifies code locations without reproducing or endorsing their engineering values.

| Family | Exact path | Examples present | Required disposition |
|---|---|---|---|
| Inline compliance defaults | `backend/app/domain/rules_engine.py::DEFAULT_RULES` | cooling flow, cooling temperature, current type, tip geometry, nugget formula | `QUARANTINE`; no automatic intake. Any later human-created disabled `DRAFT` + `UNRESOLVED` metadata candidate keeps all threshold/formula fields null and stays outside applicability, requirement, and MRC discovery until governance independently establishes a real requirement; retain legacy code only for compatibility until separately deprecated |
| Priority conflict winner | `backend/app/domain/rules_engine.py::SOURCE_PRIORITY`, `detect_conflicts` | automatically selects a priority winner and records a prose decision | `QUARANTINE`; governed conflicts require a versioned approved policy that fully resolves the conflict, otherwise `ENGINEERING_REVIEW_REQUIRED` |
| Weld parameter table/ranges | `backend/app/domain/engine.py` | thickness/material ranges, cooling conditions, risk penalties, nugget extrapolation formula | `QUARANTINE`; do not ingest as rules or evidence |
| Model candidates | `backend/app/domain/models.py`, `model_registry.py`, `model4_full.json` | OEM-table, literature-formula, DOE/polynomial outputs and source ranking | `QUARANTINE`; retain only as legacy/advisory model compatibility; future DWP references require model/dataset/artifact/applicability provenance; never convert to Registry evidence automatically |
| Electrode-life heuristics | `backend/app/domain/electrode_life.py` | life baselines, cooling/current/tip factors, dressing/stepper behavior | `QUARANTINE`; no MRC readiness or DWP release authority |
| Weld-lobe/pulse heuristics | `backend/app/domain/weld_lobe.py`, `pulse_strategy.py` | material factors, risk zones, pulse selection | `QUARANTINE`; retain advisory use only until separately validated |
| Failure-probability heuristics | `backend/app/domain/failure_probability.py` | material factors, cooling/process conditions, probability/severity mapping | `QUARANTINE`; retain regression compatibility, label advisory, never use as PASS/READY/release truth |
| Optimization/model-validation heuristics | `backend/app/domain/doe_optimizer.py`, `ensemble.py`, `polynomial_model.py`, `model_validation.py`; wired through `application/optimization_service.py` and `api/v1/optimization.py` | optimization eligibility, ensemble/confidence, polynomial output, validation status | `QUARANTINE`; retain legacy/model compatibility, but never use a current cutoff/status/result as governed rule, MRC, quality, approval, or release truth |
| Engineering signal/sensitivity/energy heuristics | `backend/app/domain/dynamic_resistance.py`, `sensitivity.py`, `energy.py`; dynamic resistance and sensitivity are wired through `application/engineering_service.py` / `api/v1/engineering.py`, while energy is currently a domain helper | curve classification, sensitivity perturbations, energy calculation/default assumptions | `QUARANTINE`; retain advisory compatibility, never treat a computed label/value as source-backed compliance or release truth |
| Material support labels | `backend/app/domain/materials.py`, consumed by `engine.py` | static supported/limited/reference-only/unsupported labels that influence legacy analysis output | `QUARANTINE`; do not convert labels into Registry applicability, evidence, PASS, READY, or release authority |

### 1.5 Baseline summary by action

- `REUSE`: layered package structure, FastAPI `/api/v1`, Pydantic contracts, JWT identity, SQLAlchemy session mechanics, Alembic convention, PostgreSQL Docker Compose runtime target, pytest/TestClient pattern, CI entry point.
- `EXTEND`: RBAC, transaction management, project/weld identity references, model exports, audit retrieval, CI, evidence and test-result linking.
- `REPLACE` for governed paths: current Rule/evaluator/conflict winner, free-text approvals, mutable current-row revision semantics, caller-supplied quality acceptance, independently committed audit publication.
- `QUARANTINE`: all hard-coded prototype/default rule, engineering, model, risk, cooling, electrode-life, and conflict-resolution values/behavior.
- `NEW`: persistent Registry, evidence and applicability revisions, immutable rule evaluations, MRC aggregate, DWP aggregate, governed audit/versioning, repository adapters, granular permissions, idempotency, reference/hash validation, historical-reproduction tests.

## 2. Approved safety invariants

Every phase, schema, service, endpoint, test, and rollout gate must enforce the following:

1. Unsupported engineering thresholds never enter the governed production path.
2. Code constants, tests, templates, generated Markdown, examples, AI-authored claims, and existing defaults are not engineering evidence.
3. Only an applicable, `ACTIVE`, verified `SOURCE_BACKED` rule may produce deterministic engineering `PASS` or `FAIL`.
4. A required applicable `PROPOSED` rule cannot support PASS/READY and routes to controlled manual review; it is distinct from an `UNRESOLVED` engineering-evidence blocker.
5. `UNRESOLVED != PASS` and `UNRESOLVED != CONDITIONAL PASS`.
6. Required applicable `UNRESOLVED` blocks automatic `READY` and maps to `ENGINEERING_REVIEW_REQUIRED` in MRC aggregation.
7. Required missing/invalid/stale/unsupported-unit input produces an explicit data condition; `DATA_INSUFFICIENT` maps to `MANUAL_REVIEW_REQUIRED` and blocks automatic `READY`.
8. Zero applicable validated rules produces `NOT_EVALUATED` unless a higher-precedence blocker exists; it never produces `READY`.
9. A required applicable `SOURCE_BACKED FAIL` produces `NOT_READY`.
10. MRC consumes Registry rule/evaluation truth; it never stores duplicate engineering thresholds.
11. DWP references exact immutable Registry evaluations and MRC decisions; it never recalculates them.
12. Human review and workflow disposition are append-only and separate from deterministic engineering truth. They never rewrite `FAIL`, `UNRESOLVED`, `DATA_INSUFFICIENT`, `NOT_READY`, or `NOT_EVALUATED` as success.
13. Completed rule evaluations, MRC decisions, DWP revisions, approvals, and releases remain historically reproducible from pinned versions/snapshots.
14. Governed state publication and its audit event are atomic or equivalently fail-closed. Audit failure prevents approval/publication/release.
15. Inactive/superseded rules cannot support a new evaluation, but historical evaluations remain bound to the exact rule revision originally used.
16. Unresolved conflicts block automatic readiness; a prototype priority ranking is never sufficient merely because it exists in code.
17. The 16 MRC inventory items stay `UNRESOLVED` until a separately governed evidence review promotes a new Registry revision.

## 3. Dependency direction and implementation order

The safest repository-specific direction is:

```text
Phase-0 decisions and shared immutable/audit contracts
  → Registry identity and revision persistence
    → Evidence references and applicability revisions
      → Rule unit/conflict/applicability evaluation
        → Immutable rule-evaluation persistence
          → MRC definitions, observations, evaluation, aggregation, review
            → DWP identity, immutable revisions, references, approval/release gates
              → API + granular RBAC exposure
                → cross-system E2E, evidence enablement, production review
```

This retains the requested conceptual direction. Shared audit/version/idempotency contracts move ahead of the first Registry migration because the first governed revision must already be immutable and auditable; retrofitting audit later would create an unsafe historical gap.

| Order | Dependency | Why it must precede the next layer |
|---|---|---|
| 0 | Architecture, identifier, transaction, hash, retention, and authorization decisions | They shape primary keys, uniqueness, immutable references, deletion behavior, and transaction boundaries |
| 1 | Registry stable identity + immutable revisions | Evidence, applicability, and evaluations require exact rule revisions, not a mutable rule row |
| 2 | Evidence + applicability + lifecycle/effective-date governance | The evaluator must prove why a rule is eligible before comparing any value |
| 3 | Unit-safe deterministic evaluation + immutable results | MRC must consume a trusted result contract and cannot duplicate comparisons |
| 4 | MRC definitions/observations/aggregation/reviews | DWP requires an exact immutable readiness assessment and blocker summary |
| 5 | DWP revisions/references/workflow | DWP composes existing truth; implementing it earlier would invite duplicated Registry/MRC calculations |
| 6 | Public API and full RBAC exposure | External access follows stable domain, transaction, idempotency, and authorization contracts |
| 7 | Integration/E2E and production integration | Cross-system behavior is meaningful only after each owner is independently tested |
| 8 | Engineering-evidence enablement and production release | Threshold-driven behavior is the last step and requires source evidence, operational policy, security, audit, and field validation |

## 4. Persistence and database plan

### 4.1 Persistence conventions

- Continue SQLAlchemy 2.x models and Alembic migrations.
- Use a stable internal primary key plus a stable human/business identifier where the designs require one (`rule_id`, `check_id`, passport identity).
- Final identifier types, UUID strategy, canonical JSON representation, and hash algorithm/version are Phase 0 decisions. They must be fixed before the first migration.
- Mutable roots may hold a controlled current-revision pointer. Every governed revision/result remains immutable after sealing/publication.
- JSON is appropriate only for versioned snapshots or trace payloads whose schema/version is stored. Searchable identity, lifecycle, evidence, state, foreign keys, and gate fields remain typed columns.
- Foreign keys point to immutable revision/result rows where historical truth is required; a mutable current row is never sufficient.
- Normal deletes are prohibited for governed historical records. Supersession/retirement and retention tombstones replace destructive deletion.
- Every governed transaction carries actor/service identity, reason where state changes, UTC time, correlation ID, idempotency key where applicable, software/schema version, and audit data.
- SQLite remains suitable for fast unit/contract tests. Migration and transactional semantics must also run against PostgreSQL because it is the repository's Docker Compose/runtime database target; the repository does not establish a current production deployment state.

### 4.2 Registry entities

| Entity / likely table | Owner and purpose | Primary identity and important foreign keys | Immutable/versioned behavior | Atomic boundary | Dependency order | Safe before thresholds resolve? |
|---|---|---|---|---|---|---|
| `EngineeringRule` / `engineering_rules` | Registry; stable identity and current-revision pointer | internal PK; unique immutable `rule_id`; optional current revision FK | Stable identity only; never stores mutable threshold truth as the sole record | identity creation + audit | R1 | Yes, empty identity shells only |
| `EngineeringRuleRevision` / `engineering_rule_revisions` | Registry; exact lifecycle/evidence/operator/unit/source/applicability metadata for one revision | immutable revision PK; rule FK; unique rule + revision; supersedes revision FK | Draft may be edited only through controlled draft workflow; activation seals content hash; published revision is immutable | revision creation/transition, prior supersession, pointer update, audit in one transaction | R1 | Yes; seed no prototype values as authority |
| `RuleLifecycleEvent` / `rule_lifecycle_events` | Registry governance; append activation, deprecation, supersession, expiry, retirement, and correction events against exact rule content | event PK; rule/revision FK; replacement revision FK when applicable; actor/authority/reason | Append-only; current/as-of lifecycle is a reproducible projection and never rewrites sealed rule content/hash | lifecycle event, current projection/pointer, and audit in one transaction | R1 | Yes |
| `EvidenceReference` / `evidence_references` | Registry evidence; controlled document/study reference, revision, exact location, availability/verification/hash | evidence revision PK; rule-revision association; optional external object ref | Append/new revision; never overwrite evidence used by an evaluation | evidence registration/verification + audit | R2 | Yes |
| `RuleApplicability` / `rule_applicabilities` | Registry; versioned material/stack/machine/equipment/category/context predicates | applicability PK; rule-revision FK; policy/schema version | Immutable with sealed rule revision; later change creates new rule revision/applicability rows | revision seal + applicability + audit | R2 | Yes |
| `RuleEvaluation` / `rule_evaluations` | Registry evaluation; pinned context, candidates, selected rules, raw/normalized inputs, result, reason codes, software/policy versions, hash | evaluation PK; exact rule-revision/evidence refs; optional project/weld/MRC context refs; correlation/idempotency uniqueness | Append-only final result; corrections/reevaluation create a new evaluation linked to prior | result, all trace rows/references, and audit publication | R3 | Yes for unresolved/not-evaluated/data-condition paths; production PASS/FAIL is evidence-gated |
| `RuleEvaluationCandidate` / `rule_evaluation_candidates` | Registry evaluation trace; every discovered candidate, applicability outcome, exclusion/conflict reason | evaluation FK + rule-revision FK | Immutable child trace | same as evaluation | R3 | Yes |
| `RuleEvaluationInput` / `rule_evaluation_inputs` | Registry evaluation trace; raw value/unit, canonical value/unit, conversion/policy version, validation state | evaluation FK; observation/external ref when present | Immutable snapshot/reference | same as evaluation | R3 | Yes |
| `RuleConflictResolution` / `rule_conflict_resolutions` | Registry; candidates, approved policy/version, resolution result or unresolved blocker | evaluation FK; policy identifier/version; selected rule revision only if fully resolved | Immutable result; policy changes require new evaluation | same as evaluation | R3 | Yes; unresolved is the safe result |

`EngineeringRuleRevision` must distinguish evidence class from lifecycle. A `DRAFT + UNRESOLVED` requirement remains discoverable as a blocker, but only `ACTIVE + SOURCE_BACKED + verified evidence` is eligible for numeric/categorical PASS/FAIL.

After rule content is sealed, activation, deprecation, supersession, expiry, and retirement are append-only `RuleLifecycleEvent` actions tied to the exact content hash. Any materialized current lifecycle/pointer is only a rebuildable projection. A threshold, formula, applicability, evidence, or other engineering-content change always creates a new rule revision; it never edits the sealed revision.

### 4.3 MRC entities

| Entity / likely table | Owner and purpose | Primary identity and important foreign keys | Immutable/versioned behavior | Atomic boundary | Dependency order | Safe before thresholds resolve? |
|---|---|---|---|---|---|---|
| `MrcCheckDefinition` / `mrc_check_definitions` | MRC; stable check ID, version, requiredness, observation contract, rule selector, review trigger | definition revision PK; stable `check_id`; prior-version link | Published versions immutable; lifecycle and content hash pinned by assessment | definition publication + audit | M1 | Yes; U-001–U-016 may be represented without thresholds |
| `MrcAssessment` / `mrc_assessments` | MRC; one contextual assessment/revision with machine/gun/station/process/material/stack/schedule snapshots | assessment PK; optional supersedes assessment; project/weld/context refs; correlation/idempotency key | Draft during capture; sealed on evaluation; reevaluation is a new assessment/revision | assessment creation/seal + audit | M2 | Yes |
| `MrcObservation` / `mrc_observations` | MRC; raw observation, unit, method/device/calibration, observer, time, quality/staleness | observation PK; assessment FK; optional supersedes observation | Append-only/correct-by-supersession; consumed value is snapshotted in result | observation append/supersede + audit | M2 | Yes |
| `MrcCheckResult` / `mrc_check_results` | MRC; check definition + Registry evaluation refs + condition/result/reasons | result PK; assessment, check-definition revision, rule-evaluation FKs | Immutable after evaluation | all results + decision + audit | M3 | Yes; unresolved/data-insufficient/not-evaluated behavior is testable now |
| `MrcReview` / `mrc_reviews` | MRC workflow; manual/engineering review trigger, role/authority, disposition, comments/attachments | review PK; assessment/check-result FK; reviewer user FK; supersession/withdrawal link | Append-only; never edits deterministic check/decision | review event + audit | M4 | Yes |
| `ReadinessDecision` / `readiness_decisions` | MRC; final deterministic state, six-prerequisite matrix, primary and secondary blockers, algorithm version/hash | decision PK; assessment FK unique for sealed evaluation; check-result refs | Immutable; new evaluation creates new assessment/decision | assessment seal, results, decision, audit publication | M3 | Yes; READY remains impossible where prerequisites fail |

### 4.4 DWP entities

| Entity / likely table | Owner and purpose | Primary identity and important foreign keys | Immutable/versioned behavior | Atomic boundary | Dependency order | Safe before thresholds resolve? |
|---|---|---|---|---|---|---|
| `DigitalWeldPassport` / `digital_weld_passports` | DWP; stable passport identity and controlled current revision pointer | passport PK; unique approved weld-identity scope; current revision FK | Stable identity; no engineering truth stored only on mutable root | identity create + audit | D1 | Yes |
| `DwpRevision` / `dwp_revisions` | DWP; immutable aggregate revision, orthogonal statuses, prior/superseding links, reason/hash | revision PK; passport FK; prior revision FK; creator user FK | Draft editable with audit/optimistic version; sealing freezes hash; approved/production revision never patched | seal/status transition/pointer update + audit | D1 | Yes |
| `DwpSectionSnapshot` / `dwp_section_snapshots` | DWP; versioned identity, stack/design, equipment snapshots with schema version/hash | snapshot PK; DWP revision FK; optional external immutable master version | Frozen with sealed DWP revision | revision seal + snapshots + audit | D2 | Yes |
| `DwpRecipeReference` / `dwp_recipe_references` | DWP; exact recipe ID/revision/hash plus decision-critical display snapshot | DWP revision FK; external recipe revision reference | Immutable; recipe change requires new DWP revision | attach/validate reference + audit; final seal includes it | D2 | Yes, though authoritative recipe ownership remains a dependency |
| `DwpMrcReference` / `dwp_mrc_references` | DWP; exact MRC assessment/decision/state/hash and blocker summary | DWP revision FK; MRC assessment and decision FKs | Immutable; never recomputed | attach reference + audit; release transaction validates it | D2 | Yes; non-READY states remain explicit |
| `DwpRuleEvaluationReference` / `dwp_rule_evaluation_references` | DWP; exact Registry evaluation/result/rule/evidence lineage | DWP revision FK; rule-evaluation FK | Immutable | attach set + audit; included in revision hash | D2 | Yes |
| `DwpQualityEvidenceLink` / `dwp_quality_evidence_links` | DWP; immutable quality/test/method/criterion/attachment link and display result | DWP revision FK; external or future quality-record ref; criterion rule/evidence ref where applicable | Append while permitted; correction supersedes; sealed change requires new revision | attach/supersede + audit | D3 | Yes for evidence capture; quality PASS is evidence-gated |
| `DwpModelResultLink` / `dwp_model_result_links` | DWP; immutable model/artifact/dataset/applicability/result reference | DWP revision FK; future model-execution ref or immutable external ref | Append-only reference; never engineering authority | attach + audit | D3 | Yes, if always advisory and explicitly governed |
| `DwpActualProcessReference` / `dwp_actual_process_references` | DWP; actual-cycle/batch or immutable raw-store reference with provenance/hash/range | DWP revision FK; external event/object ref | Append-only observation/reference; high-volume data remains external | attach + audit | D3 | Yes |
| `DwpApproval` / `dwp_approvals` | DWP workflow; exact revision hash, approval scope, durable actor/role/authority, decision | approval PK; DWP revision FK; user FK; withdrawal/supersession link | Append-only; applies to one exact revision hash | approval decision + audit | D4 | Yes, but approval cannot bypass deterministic gates |
| `DwpRelease` / `dwp_releases` | DWP workflow; release/suspend/retire event for exact revision and scope | release PK; DWP revision/approval FKs; release authority user FK | Append-only state events | gate validation, release event/status, audit in one transaction | D4 | Schema is safe; production RELEASE remains blocked |
| `DwpWorkflowDisposition` / `dwp_workflow_dispositions` | DWP workflow; request/acknowledgment/concession metadata separate from truth | disposition PK; revision/blocker refs; actor/authority/expiry | Append-only; never updates deterministic results | disposition + audit | D4 | Yes; concession effect remains policy-blocked |

The sealed `DwpRevision` content and content hash are never changed by later approval, release, suspension, retirement, or disposition actions. Those actions are append-only events against the exact revision hash. Any displayed “current” approval/release/lifecycle state is a derived, reproducible projection of that event stream (with an as-of view available), not a mutation of the sealed engineering payload.

### 4.5 Shared governance entities and metadata

| Entity / structure | Owner and purpose | Identity / links | Immutable/versioned behavior | Atomic boundary | Dependency order | Safe before thresholds resolve? |
|---|---|---|---|---|---|---|
| `GovernedAuditEvent` / `governed_audit_events` | Shared governance; authoritative event for Registry/MRC/DWP writes | event PK; actor/service FK; entity type/ID/revision; correlation/idempotency; prior/new hash | Append-only; corrections are later linked events | Inserted in the same DB transaction as the governed state change | G0, before the first publishable Registry command | Yes; required before publication endpoints |
| `ContentVersionMetadata` fields | Owning aggregate; schema version, canonicalization version, content hash algorithm/value, software build/version | embedded on immutable revision/result/event rows | Frozen with owner row; a new owner revision/result carries changed metadata | Committed with the owning revision/result/event | G0 shared value contract, then embedded from R1 onward | Yes |
| Actor/reason metadata | Owning aggregate/event; durable user/service, role/authority snapshot, change reason, timestamp | user/service reference plus display snapshot | Frozen with event/revision; later action is a new event | Committed with the owning governed action | G0 shared value contract, then embedded from R1 onward | Yes |
| External immutable reference envelope | Shared contract; URI/object ID, owner, revision, hash, media/schema, retention/access, availability | stored by each owner or shared value object | Reference update creates a new owner revision or superseding link | Attach/validate/reference audit commit with its owner action | G0 contract; used by R2, M2, and D2/D3 | Yes |

The existing `audit_logs` table may continue for legacy events. Governed publication must not depend on calling the current `write_audit()` after a separate commit.

### 4.6 Conceptual migration order

No migration is created by this plan. Future migrations should remain small and dependency-ordered:

1. **Migration R1 — Registry identity/revisions + governed audit foundation.** Create shared audit/version metadata and Registry root/revision structures. No rule values are seeded.
2. **Migration R2 — Evidence/applicability.** Add evidence revisions, rule-evidence associations, applicability predicates, lifecycle constraints, and indexes.
3. **Migration R3 — Rule evaluations.** Add immutable evaluation, candidate/input/conversion/conflict trace structures and idempotency uniqueness.
4. **Migration M1 — MRC definitions.** Add versioned check definitions. If U-001–U-016 identifiers are seeded, seed only threshold-free unresolved metadata/selectors and preserve the exact inventory.
5. **Migration M2/M3 — MRC assessments.** Add assessments, observations, results, decisions, reviews, immutable/supersession constraints, and audit relationships.
6. **Migration D1/D2 — DWP identity/revisions/references.** Add passport roots, revisions, snapshots, Registry/MRC/recipe references, ETag/version fields, and retention protections.
7. **Migration D3/D4 — DWP evidence/governance.** Add actual/quality/model links, approvals, releases, dispositions, and governed audit relationships.
8. **Hardening migrations.** Add performance indexes, online/validated refinements, and PostgreSQL-specific optimizations after load/concurrency testing. Correctness constraints—identity/revision uniqueness, required foreign keys, immutability/supersession shape, and retention/deletion protection—ship with the migration that introduces each owner table, before any governed writes.

Each migration gate requires: generated SQL review, empty and representative upgrade, downgrade in a disposable environment where supported, PostgreSQL validation, no prototype-rule data migration, constraint tests, and an explicit rollback/forward-fix procedure. Production historical tables must never be dropped by routine application cascades.

## 5. Prototype rule migration strategy

### 5.1 Required dispositions

No prototype value is silently copied into a governed Registry revision.

| Prototype family | Initial disposition | Optional future intake | Removal path |
|---|---|---|---|
| `rules_engine.DEFAULT_RULES` | `QUARANTINE` from all new services | No automatic intake. A later, separately approved human intake may create a disabled `DRAFT` + `UNRESOLVED` candidate carrying identity/name/prototype provenance only; threshold/operator/formula fields remain null, and it remains excluded from applicability/requirement/MRC discovery until governance independently establishes a real requirement | Separate legacy evaluator deprecation after consumers migrate and regression impact is approved |
| Automatic source-priority conflict winner | `QUARANTINE` | Reimplement only as an explicitly versioned, approved conflict-policy adapter; unresolved conflicts remain blockers | Remove later with legacy evaluator |
| `engine.py` tables/ranges/formulas and cooling checks | Retain only for legacy endpoint/test compatibility | No automatic Registry intake | Separate engineering-model validation/deprecation plan |
| `models.py` / `model_registry.py` candidates | Retain as advisory prototypes | Future model-governance record may reference artifact/source/validation status; it still cannot become a rule without Registry evidence review | Separate model-registry hardening plan |
| electrode-life, weld-lobe, pulse, failure-probability heuristics | Retain as advisory prototypes | DWP may later reference immutable advisory executions after provenance support exists | Separate module-specific validation/deprecation plan |

### 5.2 Controls preventing accidental `SOURCE_BACKED` promotion

1. New Registry persistence starts empty; no migration imports constants.
2. `SOURCE_BACKED` creation is not a normal create-draft field. It requires a dedicated evidence-review/activation command.
3. Promotion requires controlled evidence ID/revision, exact location, availability/verification, applicability, units, operator/formula, reviewer with delegated engineering authority, change reason, and content hash.
4. Author and evidence reviewer/activator are distinct where separation policy requires it.
5. Database/service invariants reject `ACTIVE + SOURCE_BACKED` without verified evidence and complete applicability/unit metadata.
6. Imports label origin (`legacy_prototype`, `test_fixture`, `template`, or controlled evidence). Non-controlled origins are ineligible for promotion.
7. A `legacy_prototype` candidate is quarantined metadata, not an applicable requirement. Import alone cannot add an MRC blocker or engineering obligation; deliberate human governance must establish requirement identity/applicability independently of the code claim.
8. Registry APIs never infer evidence class from source-name text such as “OEM,” “ISO,” “AWS,” “company standard,” or “literature.”
9. Static architecture tests forbid imports from `app.domain.rules_engine.DEFAULT_RULES` and quarantined modules into new Registry/MRC/DWP packages.
10. Regression tests assert that legacy constants cannot appear in governed Registry rows or produce governed PASS/READY/release decisions.
11. Activation is atomic with audit; an audit failure leaves the candidate unactivated.
12. Periodic governance queries list active rules without complete evidence, unexplained provenance, missing hashes, or invalid applicability. Any result is a release blocker.
13. Prototype removal occurs only in a separate approved deprecation change; this plan does not modify current behavior.

## 6. Service-layer plan

Service names follow the requested terminology and current `backend/app/application/*_service.py` convention. Domain policies remain pure; repositories own persistence; API adapters own HTTP concerns.

| Service | Responsibility | Dependencies | Deterministic vs workflow | Fail-safe behavior | Test boundary / order |
|---|---|---|---|---|---|
| `AuditVersioningService` | Canonical revision metadata, content hash envelope, governed audit event construction, transaction participation | clock/actor/build metadata, audit repository | Deterministic metadata + infrastructure coordination; no engineering decision | If required audit cannot persist, governed publication fails and rolls back | First; transaction rollback, hash stability, actor/reason/correlation tests |
| `RuleRegistryService` | Stable rule identity, draft revision lifecycle, activate/supersede/retire commands, history | rule repository, evidence service, authorization policy, audit/versioning | Workflow/governance; never evaluates measurements | Reject destructive edit, invalid transition, unverified activation, duplicate active revision | R1; lifecycle/state-machine and persistence tests |
| `RuleEvidenceService` | Register/verify/supersede evidence, enforce classification/promotion requirements | evidence repository, actor authority, audit/versioning | Governance workflow; evidence eligibility checks are deterministic | Unavailable/unverified evidence cannot support activation or PASS/FAIL | R2; classification, provenance, exact-location, promotion negative tests |
| `RuleApplicabilityService` | Resolve candidate rules and requirement records for a pinned context/as-of time | Registry read repository, versioned applicability policy | Deterministic | Zero validated candidates returns explicit no-rule outcome; unresolved requirements remain visible | R2/R3; dimension matrices, effective dates, inactive/superseded behavior |
| `RuleEvaluationService` | Validate input/unit, resolve conflicts, evaluate eligible rules, create immutable trace/result | applicability, evidence, unit/conversion policy, conflict policy, audit/versioning, evaluation repository | Deterministic engineering truth only | Only active verified source-backed rules can PASS/FAIL; all uncertainty is explicit; persistence/audit failure publishes no result | R3; exhaustive result/reason/unit/conflict/idempotency tests |
| `MachineObservationService` | Capture/supersede observations with method/device/calibration/time/quality metadata | MRC repository, unit metadata, authorization, audit/versioning | Data workflow; no readiness truth | Missing/invalid/stale/unsupported data remains explicit and cannot be coerced | M2; validation, supersession, role/scope tests |
| `MachineReadinessService` | Create/pin assessment context/definitions, invoke Registry evaluations, aggregate all blockers, publish immutable decision | MRC repository, RuleEvaluationService, audit/versioning | Deterministic orchestration and aggregation | Uses exact precedence; no Registry/audit availability means no authoritative READY publication | M3; six READY prerequisites, mixed precedence, 16 unresolved path, historical replay |
| `MRCReviewService` | Append manual/engineering reviews and workflow dispositions | MRC repository, authorization/authority policy, audit/versioning | Human workflow only | Cannot mutate check results or final deterministic state; reevaluation creates a new assessment | M4; separation, permission, immutable truth tests |
| `DWPRevisionService` | Create draft from prior revision, manage ETags, snapshots/references, seal immutable revision, supersede | DWP repository, reference validators, audit/versioning | Deterministic revision mechanics + workflow | Broken/mutable references or audit failure prevent seal; sealed revision cannot be patched | D1/D2; immutability, hash, optimistic concurrency, supersession tests |
| `DigitalWeldPassportService` | Compose passport sections and exact Registry/MRC/recipe/quality/model/actual references; derive completeness; govern submit/approval/release commands | DWPRevisionService, Registry/MRC read ports, authorization/release policy, audit/versioning | Composition plus workflow; never recalculates Registry/MRC | Preserves all blocker states; failed reference/gate/audit blocks transition/release | D2–D4; reference integrity, truth/disposition separation, release negative tests |
| `DWPApprovalReleaseService` (may be part of `DigitalWeldPassportService`) | Revision-scoped approval, release, suspension, retirement, separation of duties | authorization/authority/release policy, DWP repo, audit/versioning | Human governance workflow | No release unless every policy gate is affirmatively satisfied; no concession effect until policy is approved | D4; authorization, replay, atomic audit, idempotency tests |

Recommended service implementation order:

1. shared threshold-free types and `AuditVersioningService` contracts;
2. `RuleRegistryService`;
3. `RuleEvidenceService`;
4. `RuleApplicabilityService`;
5. `RuleEvaluationService`;
6. `MachineObservationService`;
7. `MachineReadinessService`;
8. `MRCReviewService`;
9. `DWPRevisionService`;
10. `DigitalWeldPassportService` and approval/release workflow;
11. API adapters and production integrations.

The first `RuleRegistryService` slice implements identity, draft revision, and history only. Evidence-dependent activation is added only after `RuleEvidenceService` and atomic governed audit are complete; production activation remains behind its GO gate.

## 7. Rule-evaluation foundation

Rule evaluation is implemented and verified before MRC. The evaluator is a pure domain policy invoked by an application service; it does not read environment variables, open database sessions, or raise FastAPI exceptions.

### 7.1 Required separation of fields

Do not overload one `status` field. At minimum preserve independently:

- rule evidence class: `SOURCE_BACKED`, `PROPOSED`, `UNRESOLVED`;
- rule lifecycle: `DRAFT`, `REVIEW`, `ACTIVE`, `DEPRECATED`, `SUPERSEDED`, `EXPIRED`;
- applicability outcome and reasons;
- deterministic rule outcome/condition: `PASS`, `FAIL`, `UNRESOLVED`, `NOT_EVALUATED`, `DATA_INSUFFICIENT`, plus explicit unit/conflict/evidence/error conditions;
- review requirement: engineering or manual;
- workflow disposition;
- consumer aggregate state, such as the MRC final state.

`safe_default` is metadata controlling fail-safe routing. It cannot manufacture a threshold, PASS, FAIL, or readiness decision.

### 7.2 Deterministic evaluation pipeline

1. **Validate request envelope.** Require a context ID/snapshot, as-of time, requester/service identity, and correlation ID. Validate the structure of every supplied observation/value/unit object, but do not reject an otherwise valid evaluation request merely because a required observation or unit is absent; that absence must be persisted as `DATA_INSUFFICIENT` and routed to manual review. Reject only structurally malformed envelope/metadata that cannot be represented safely.
2. **Discover applicable requirements.** Resolve all matching requirement records, including required `DRAFT/UNRESOLVED` requirements. Never filter only `ACTIVE` rules before unresolved discovery.
3. **Resolve validated candidates.** Separately select enabled, effective, unexpired, `ACTIVE + SOURCE_BACKED` revisions with available/verifiable evidence and matching applicability.
4. **Pin versions.** Pin every candidate rule revision, evidence revision, applicability-policy/schema version, context hash, unit-catalog version, conflict-policy version, and evaluator/software version.
5. **Handle zero validated candidates.** Preserve discovered unresolved requirements. If no higher blocker exists and no applicable validated rule exists, result is `NOT_EVALUATED`; it is never PASS.
6. **Resolve conflicts.** Retain every candidate. Apply only an approved, versioned deterministic conflict policy that fully resolves the conflict. Otherwise emit `RULE_CONFLICT` and engineering review; no prototype priority winner is used.
7. **Validate required inputs.** Missing required value or required unit is `DATA_INSUFFICIENT`; invalid, stale, non-finite, out-of-domain, or context-incomplete data receives a stable condition/reason and cannot be evaluated.
8. **Validate dimensions and units.** Conversion is allowed only through a versioned approved catalog after dimensional compatibility is proven. Record raw and normalized values, formula/catalog version, rounding policy, and outcome. No silent conversion or coercion.
9. **Evaluate eligible rules only.** Only an applicable, active, verified source-backed revision can produce PASS or FAIL. Formula/custom operators execute only from a controlled versioned evaluator implementation tied to the rule revision.
10. **Persist immutable result.** Store result, all candidates/exclusions, evidence and context snapshots, inputs/conversions, conflict trace, reason codes, software versions, hash, and audit event atomically.
11. **Return the stored representation.** GET/history routes retrieve the pinned result; they never recompute it against current data.

### 7.3 Required and optional semantics

- Requiredness belongs to the consuming rule/check contract and is versioned.
- Missing required input always blocks automatic success.
- Optional input/check skipping is permitted only when the pinned definition explicitly says optional. Record `SKIPPED_OPTIONAL`; it never satisfies a required READY prerequisite.
- A required unresolved requirement remains visible even if it is not active/evaluable.
- A required applicable `PROPOSED` rule remains non-evaluable for PASS/FAIL, blocks automatic READY, and produces a controlled manual-review condition rather than engineering approval.
- Applicability false is distinct from missing applicability context. Missing context is not “not applicable”; it is an insufficient/manual-review condition.

### 7.4 Conflict behavior

The persisted conflict trace includes candidate rule revisions, evidence classes/references, applicability results, policy ID/version, comparison details, selected revision if fully resolved, and resolution reason. If the approved policy cannot establish one complete deterministic result, emit `ENGINEERING_REVIEW_REQUIRED`. The current static `SOURCE_PRIORITY` map is never imported into the governed evaluator.

### 7.5 Superseded and inactive behavior

- New evaluations use the revision effective for the pinned context date and lifecycle rules.
- An inactive, deprecated, expired, or superseded revision cannot support current PASS/FAIL/READY unless the approved as-of policy says it was active for a historical context being reconstructed.
- Historical evaluation reads use the exact pinned revision and never substitute the current revision.
- Rollback creates a new revision with a new effective date; it does not rewrite prior effective dates or hashes.

### 7.6 Stable reason-code families

The implementation should version a machine-readable catalog, including at least:

- `RULE_PASS`, `RULE_FAIL`, `RULE_UNRESOLVED`, `RULE_PROPOSED`;
- `NO_APPLICABLE_VALIDATED_RULE`, `RULE_NOT_EFFECTIVE`, `RULE_SUPERSEDED`, `RULE_DISABLED`;
- `EVIDENCE_UNAVAILABLE`, `EVIDENCE_UNVERIFIED`;
- `REQUIRED_INPUT_MISSING`, `INPUT_INVALID`, `INPUT_STALE`, `CONTEXT_INSUFFICIENT`;
- `UNIT_MISSING`, `UNIT_UNSUPPORTED`, `UNIT_DIMENSION_MISMATCH`, `UNIT_CONVERSION_FAILED`;
- `RULE_CONFLICT_UNRESOLVED`, `CONFLICT_POLICY_UNAVAILABLE`;
- `EVALUATION_PERSISTENCE_FAILED`, `AUDIT_PERSISTENCE_FAILED`, `REFERENCE_BROKEN`.

The names are implementation contracts, not engineering values. The final catalog must be reviewed and versioned before external API freeze.

## 8. MRC implementation plan

### 8.1 Exact state model

MRC final states are exactly:

- `READY`
- `NOT_READY`
- `ENGINEERING_REVIEW_REQUIRED`
- `MANUAL_REVIEW_REQUIRED`
- `NOT_EVALUATED`

`DATA_INSUFFICIENT` remains an evaluation/input condition, not a final MRC state.

### 8.2 Exact aggregation precedence

All primary and secondary blockers are persisted even when an earlier state wins:

1. Any required applicable `SOURCE_BACKED FAIL` → `NOT_READY`.
2. Otherwise, any required applicable `UNRESOLVED`, required unavailable/unverifiable evidence, or unresolved engineering conflict → `ENGINEERING_REVIEW_REQUIRED`.
3. Otherwise, any required applicable `PROPOSED` rule, `DATA_INSUFFICIENT`, invalid/stale/unsupported-unit required input, absent required observation, explicit manual judgment, or safely persisted recoverable evaluation exception → `MANUAL_REVIEW_REQUIRED`.
4. Otherwise, zero applicable validated rules → `NOT_EVALUATED`.
5. Otherwise, and only if all six READY prerequisites pass → `READY`.

An unexpected exception may map to manual review only when a complete immutable error result and audit event are safely persisted. Otherwise no authoritative decision is published.

### 8.3 Six READY prerequisites

READY is permitted only when all are true:

1. At least one applicable validated engineering rule exists.
2. Every required applicable `SOURCE_BACKED` rule passes.
3. All required inputs are available and valid.
4. No required applicable `UNRESOLVED` rule exists.
5. No unresolved conflict exists.
6. No manual-review condition exists.

### 8.4 MRC delivery slices

1. **Definitions.** Implement threshold-free, immutable check-definition versions, rule selectors, categories, requiredness, observation contracts, review triggers, lifecycle, and hashes.
2. **Inventory representation.** Preserve exactly `U-001` through `U-016`, current counts `SOURCE_BACKED=0`, `PROPOSED=0`, `UNRESOLVED=16`. Required category discovery includes `EQUIPMENT`, `MACHINE`, `ELECTRODE`, `COOLING`, `PARAMETER`, and `MATERIAL`; U-007 and U-016 must not be omitted. Priority labels prioritize evidence work and never bypass an applicable required item.
3. **Assessment creation.** Capture/pin machine, gun, station/robot/operation, project/weld-point, process/schedule, material/stack, electrode, customer/OEM, configuration, check-definition, policy, software, and correlation context. Unknown master systems use versioned external references plus decision-critical snapshots.
4. **Observation capture.** Append typed raw observations with supplied units, methods/devices/calibration, observer, source time/time-zone, quality/freshness, attachments, and supersession.
5. **Rule resolution.** Invoke Registry applicability/evaluation services. MRC stores references and check-level orchestration metadata, never copied thresholds.
6. **Check evaluation.** Create immutable check results referencing exact Registry evaluations and preserving unresolved/data/conflict conditions.
7. **Aggregation.** Evaluate the six-prerequisite matrix and exact precedence, retaining all secondary blockers and algorithm version/hash.
8. **Review workflow.** Append manual/engineering review records and the approved dispositions `RETURN_FOR_DATA`, `REQUEST_ENGINEERING_EVIDENCE`, `ACKNOWLEDGED_BLOCKED`, `CANCELLED`, and `REEVALUATE` without editing deterministic results. A reevaluation creates a new assessment/decision linked to the prior one.
9. **Audit publication.** Persist check results, decision, sealed assessment, idempotency outcome, and governed audit in one transaction.
10. **Historical retrieval.** Return pinned snapshots/results without recalculation; provide revision/supersession and blocker histories.

### 8.5 MRC enablement boundary

MRC architecture and unresolved/manual-review flows are safe to implement now. Automatic READY remains naturally unavailable wherever a required applicable unresolved item exists, required data is insufficient, a conflict exists, or zero validated applicable rules exist. No feature or operator may force those conditions into READY.

The 16 items can be promoted only through new reviewed Registry revisions backed by qualifying engineering evidence. MRC code and check definitions must not be edited merely to insert thresholds; they resolve Registry versions dynamically and retain historical pins.

## 9. DWP implementation plan

### 9.1 Ownership and non-duplication

DWP owns passport identity, immutable revisions, snapshots/references, completeness, lifecycle, approvals, releases, dispositions, audit, and reporting. It does not own Registry applicability/evaluation or MRC check/aggregation logic.

### 9.2 DWP delivery slices

1. **Stable identity.** Define the approved weld-identity uniqueness scope and create `DigitalWeldPassport` with a controlled current-revision pointer. Do not reuse mutable `WeldPoint` as the passport revision.
2. **Immutable revision mechanics.** Create draft from identity or prior revision, require reason, use optimistic concurrency/ETags, calculate versioned content hash at seal, forbid sealed edits, and link superseding revisions.
3. **Project/weld identity snapshot.** Store exact project/program/platform/customer, part/revision, station/robot/gun/operation, point code, criticality, source IDs/versions, and schema/hash. Snapshot decision-critical mutable values.
4. **Stack/material snapshot.** Preserve ordered layers, material identities, thicknesses/units, coating/adhesive/geometry context, unknowns, and source version/hash. This is a snapshot/reference, not a new material master.
5. **Equipment snapshot.** Preserve machine/controller/transformer/gun/electrode/configuration/cooling identity and source version/hash. Missing master-data ownership remains a deployment blocker, not a reason to invent values.
6. **Recipe reference.** Pin exact recipe ID/revision/hash and a decision-critical values/units display snapshot. A dedicated recipe owner is still required before production.
7. **MRC reference.** Attach exact assessment/decision revision/hash, final state, prerequisite and blocker summary, context and software/check-definition versions. Never reconstruct or change MRC state.
8. **Rule/evidence lineage.** Attach exact immutable Registry evaluation references, including PASS, FAIL, UNRESOLVED, NOT_EVALUATED, data/review conditions, evidence, applicability, conflicts, units, and evaluator versions.
9. **Actual process references.** Store small immutable cycle facts or external immutable controller/MES/SCADA/object references with schema, provenance, hash, time range, sample count, retention, and availability. Do not turn DWP into a raw time-series store.
10. **Quality evidence.** Attach typed immutable evidence with test/specimen/batch, method/procedure/calibration, values/units, criterion rule/evidence revision, raw attachments, deterministic status, actor/time, and correction chain. Existing `TestResult.acceptance_status` alone never establishes PASS.
11. **Model results.** Attach immutable advisory result references with model/artifact/dataset versions, applicability/domain/extrapolation, inputs/outputs/units, confidence, explanation, warnings, software, and review. Model output cannot establish compliance/readiness/release.
12. **Completeness and lifecycle.** Derive completeness independently from engineering, MRC, quality, approval, release, and disposition dimensions. Lifecycle labels never imply those truths. Post-seal workflow state is projected from immutable events and never rewrites sealed revision content.
13. **Approval/release.** Append actions against one exact sealed revision hash using durable actor/authority and separation-of-duties checks. Derive the current/as-of approval and release projections from those events. Until policies and implementations pass all gates, release commands remain unavailable or fail closed.
14. **Audit/history/reporting.** Persist every state event atomically and generate reports only as derived artifacts carrying source revision/hash and generator/template versions.

### 9.3 Exact DWP dimensions to preserve

Record lifecycle:

`CREATED`, `DRAFT`, `ENGINEERING_DEFINED`, `VALIDATION_PENDING`, `VALIDATED`, `APPROVED`, `PRODUCTION_ACTIVE`, `SUPERSEDED`, `RETIRED`, `ARCHIVED`.

Orthogonal states:

- completeness: `INCOMPLETE`, `COMPLETE`, `DATA_INSUFFICIENT`;
- MRC: the exact five MRC states;
- engineering compliance: `PASS`, `FAIL`, `UNRESOLVED`, `NOT_EVALUATED`, `ENGINEERING_REVIEW_REQUIRED`, `MANUAL_REVIEW_REQUIRED`;
- quality: `NOT_STARTED`, `PENDING`, `PASS`, `FAIL`, `DATA_INSUFFICIENT`, `NOT_EVALUATED`, `REVIEW_REQUIRED`;
- approval: `NOT_SUBMITTED`, `PENDING`, `APPROVED`, `REJECTED`, `WITHDRAWN`;
- release: `NOT_RELEASED`, `RELEASED`, `SUSPENDED`, `RETIRED`;
- workflow disposition: `NONE`, `RETURN_FOR_DATA`, `REQUEST_ENGINEERING_REVIEW`, `CONCESSION_REQUESTED`, `CONCESSION_GRANTED`, `REJECTED`, `CANCELLED`.

For a sealed revision, approval, release, lifecycle-transition, and disposition values are reproducible projections from append-only events tied to that exact revision hash. They are not mutable fields written back into the sealed engineering payload.

A passport may exist with any MRC state. Under the current approved boundary, production release is blocked unless the exact referenced assessment satisfies the approved qualifying MRC requirement; automatic release assumes `READY`. Concession-based production release is an unresolved governance decision and is not implemented by this plan.

## 10. Audit and historical reproducibility

### 10.1 Required metadata

Every governed event/result/revision records or immutably references:

- stable aggregate ID, immutable revision/result/event ID, prior/superseding IDs;
- content hash, canonicalization/schema version, hash algorithm/version;
- actor/service ID, role, delegated authority and scope snapshot;
- action, reason code/text, UTC timestamp, relevant source time/time-zone/clock context;
- correlation/request ID and idempotency key;
- before/after values for controlled draft changes or before/after hashes for sealed records;
- exact rule, evidence, applicability, conflict-policy, conversion-catalog, evaluation, check-definition, MRC, recipe, material/equipment snapshot, quality, model, DWP and software/build versions as relevant;
- source/object URI, revision, hash, retention/access classification, and availability for external references;
- supersession, withdrawal, suspension, retirement, correction, or reference-repair links.

### 10.2 Operations that must be atomic

The following domain write, resulting state/revision, idempotency record, and primary audit event commit together or all roll back:

- rule revision creation when governed, evidence verification, activation, supersession, retirement;
- rule evaluation publication and its candidate/input/conflict trace;
- MRC observation supersession, assessment sealing, check results, final readiness decision, and reviews/dispositions;
- DWP revision seal, reference attachment where state-affecting, approval, release, suspension, supersession, retirement, and disposition;
- quality/model/actual-evidence correction when it affects a sealed DWP revision;
- authorization/delegation changes that grant engineering review, approval, or release authority.

The new governed audit writer joins the caller-owned transaction and performs no independent commit. Optional external telemetry, notification, or immutable archive delivery occurs through an outbox after the authoritative commit. An unavailable external sink may trigger operational escalation, but it cannot fabricate a successful governed event.

### 10.3 Historical reconstruction contract

- Reconstruct using pinned immutable rows and snapshots, never mutable “current” lookups.
- Registry change creates a new rule revision and new evaluation; prior evaluation is unchanged.
- MRC reevaluation creates a new linked assessment/decision; prior assessment is unchanged.
- DWP correction or newer Registry/MRC reference creates a new DWP revision; prior sealed revision is unchanged.
- GET/history/report endpoints do not recompute results.
- If an external record becomes unavailable, preserve the stored hash/display snapshot and mark `BROKEN_REFERENCE`; block affected gates and repair by audited new reference/revision.
- Routine project/weld deletion cascades must not delete governed historical records. Retention/tombstone/legal-hold rules are a production gate.

## 11. Authorization plan

### 11.1 Existing foundation and required extension

Reuse JWT authentication, `User`, `get_current_user`, and permission dependencies. Do not create a second authentication system. Extend authorization with:

- named granular permissions;
- project/customer/site/machine resource scope;
- explicit delegated engineering-review, approval, and release authority;
- service identities for automatic evaluation distinct from human reviewers;
- authority snapshot at decision time;
- separation of creator/reviewer/approver/releaser where approved policy requires it;
- deny-by-default behavior for unknown roles and permissions.

The current JWT subject is `User.email`, not the durable numeric user ID. Every governed action must authenticate normally, resolve the current `User` record, then persist `User.id` and the decision-time role/authority/scope snapshot; a token subject string alone is not a durable engineering actor reference. Phase 0 must also decide token subject migration/compatibility, service identities, refresh rotation/revocation, and constrained role assignment.

The current implementation gives System Admin `{"*"}`, and `require_permission()` therefore lets that wildcard satisfy every permission string. The new governed authority layer must not reuse that behavior as proof of engineering or release authority: administrative access and explicitly delegated engineering/release authority remain separate, even when one user holds both through approved assignments.

### 11.2 Conceptual permissions and proposed role intent

Role mapping is proposed for security-owner approval; it is not silently activated.

| Subsystem/action | Permission | Proposed existing-role intent | Additional control |
|---|---|---|---|
| Registry view/history | `registry:read`, `registry:audit-read` | engineering/quality/read roles within scope | evidence sensitivity and audit-access scope |
| Create/edit draft | `registry:draft-create`, `registry:draft-write` | Process/Manufacturing Engineer with scope | cannot activate own revision when separation is required |
| Evidence review | `registry:evidence-review`, `registry:review` | delegated Process/Quality engineering authority | exact evidence revision/location and reviewer authority |
| Activate | `registry:activate` | explicitly delegated engineering authority | no wildcard-admin implication; atomic audit; optional two-person rule |
| Supersede/retire | `registry:supersede` | delegated registry owner | mandatory reason and replacement/effective-date policy |
| MRC read/audit | `mrc:read`, `mrc:audit-read` | scoped engineering, maintenance, operator/read roles as policy permits | evidence detail may require stronger access |
| Create assessment | `mrc:create` | Process/Manufacturing/Maintenance as approved | project/machine scope |
| Submit observation | `mrc:observe` | Operator/Maintenance/engineering | observer/device/source identity; cannot set readiness |
| Evaluate | `mrc:evaluate` | authorized service identity or engineering role | deterministic service; no human override |
| Manual review/disposition | `mrc:manual-review`, `mrc:disposition` | scope-appropriate Maintenance/Quality/Engineering | cannot alter deterministic result |
| Engineering review | `mrc:engineering-review` | delegated engineering authority | evidence/applicability resolution creates new Registry/MRC revisions |
| DWP read/audit | `dwp:read`, `dwp:audit-read` | scoped engineering/quality/read/customer roles | customer/project/evidence access boundaries |
| Create/revise/draft write | `dwp:create`, `dwp:revise`, `dwp:draft-write` | Process/Manufacturing Engineer | ETag, reason, exact project/weld scope |
| Attach evidence | `dwp:evidence-attach`, `dwp:quality-write`, `dwp:model-attach` | Quality/Process/authorized services by evidence type | reference integrity and source authority |
| Submit | `dwp:submit` | authorized engineering author | completeness only; does not imply validation/approval |
| Engineering approval | `dwp:engineering-approve` | delegated approver | exact revision hash; separation of duties |
| Production release | `dwp:production-release` | separately delegated release authority | all deterministic gates, policy version, atomic audit |
| Supersede/suspend/retire | `dwp:supersede`, `dwp:release-manage` | delegated release owner | mandatory reason and immutable replacement/event links |

### 11.3 Missing authorization decisions

Before permission implementation: approve the role-to-permission matrix; resource scope source; delegated-authority representation; service identity model; evidence visibility; audit access; author/reviewer/approver/releaser separation; temporary delegation/expiry; emergency access; denied-action audit policy; and whether any concession authority exists. No concession effect is implemented until explicitly approved.

## 12. API rollout sequence

All routes remain under `/api/v1`, use typed Pydantic contracts, stable reason codes, JWT, resource-scope authorization, explicit engineering state in the response, and OpenAPI. HTTP 2xx never means PASS, READY, approved, or released unless the body explicitly records the governed state.

### 12.1 Cross-cutting API rules

- Create/evaluate/attach/review/approve/release/supersede commands require idempotency keys.
- Draft PATCH requires an ETag/version precondition; sealed resources reject mutation.
- Each command returns correlation ID, immutable result/revision reference when created, explicit state, and blocker/reason codes.
- Domain/application errors map to a versioned structured error body; application services do not raise FastAPI exceptions.
- GET returns persisted pinned state and supports pagination/filtering; it never evaluates on read.
- A governed command acknowledges success only after domain write and audit commit.
- Registry/evidence/reference/audit unavailability fails closed for publication operations.

### 12.2 Phased endpoint groups

| Phase | Conceptual routes | Request/response role | Authorization | Failure behavior | Idempotency / transaction |
|---|---|---|---|---|---|
| A — Registry read/governance | `GET/POST /rules`, `GET /rules/{rule_id}`, `GET /rules/{rule_id}/revisions`, `POST /rules/{rule_id}/revisions`, `POST /rules/{rule_id}/activate`, `POST /rules/{rule_id}/supersede`, evidence register/review routes | Create/list immutable identities/revisions/evidence and govern lifecycle; no implicit evaluation | registry read/draft/review/activate/supersede plus scope/authority | invalid lifecycle/evidence/authority returns stable blockers; no partial activation | idempotency on create/transition; revision/evidence/transition/audit atomic |
| B — Rule evaluation | `POST /rule-evaluations`, `GET /rule-evaluations/{id}`, trace/history queries | Accept pinned context and typed inputs; return immutable results/candidates/reasons/hash | evaluation permission/service identity plus resource scope | missing/unresolved/conflict/data/unit/evidence conditions are successful explicit domain results where safely persisted; infrastructure failure publishes none | evaluate is idempotent; full trace/result/audit atomic |
| C — MRC | `POST /mrc/assessments`, observation routes, `POST .../evaluate`, assessment/check/history GET, review routes | Create assessment, append observations, publish immutable decision, append separate reviews | MRC create/observe/evaluate/review/audit permissions | Registry/evidence/audit failure blocks finalization; non-READY is explicit, not HTTP failure | idempotency for create/observe/evaluate/review; final results/decision/audit atomic |
| D — DWP | `POST /dwp`, `POST /dwp/{id}/revisions`, draft PATCH, reference/evidence attach routes, submit/approve/release/supersede, GET revision/history | Build/seal immutable revision and reference exact upstream truth | granular DWP permissions, scope, delegated approval/release, separation | broken reference, stale ETag, incomplete data, nonqualifying MRC, unresolved/quality blocker, audit failure prevents transition/release | idempotency for commands; ETag for draft; every state transition/audit atomic |
| E — Review/audit | scoped Registry/MRC/DWP review queues, `/.../{id}/audit`, cross-reference trace queries | Query or append reviews without changing deterministic truth | matching review/audit permissions and evidence sensitivity | unauthorized data omitted/forbidden; audit query failure never causes recomputation | review writes idempotent/atomic; reads paginated |
| F — Production integration | controller/MES/SCADA/object/quality/model reference intake and release integration | Register immutable external references/events; never trust caller status alone | service identity, deployment scope, ingestion/release permission | provenance/hash/schema/time/reference failure quarantines input and blocks affected gate | external event ID + idempotency; outbox/retry; governed link/audit atomic |

Final path names should be frozen during API review. Document 111’s older `/evaluate` proposal should be normalized to a resource-oriented `/rule-evaluations` contract if approved; this changes naming only, not Registry ownership or evaluation semantics.

## 13. Test strategy

### 13.1 Test infrastructure changes

- Retain fast SQLite unit/service tests where behavior is database-neutral.
- Add Alembic upgrade tests from an empty database rather than relying only on `Base.metadata.create_all`.
- Add PostgreSQL integration coverage for constraints, JSON behavior, locking, idempotency, optimistic concurrency, indexes, and transaction rollback.
- Add deterministic clocks/IDs/build versions and unmistakably synthetic non-engineering fixtures.
- Add an import-boundary test proving new Registry/MRC/DWP modules do not import quarantined prototype constants/evaluators.
- Preserve the current 17-test baseline and existing API behavior until a separate approved migration/deprecation change.

### 13.2 Unit matrix

| Area | Required tests |
|---|---|
| Evidence classification | exact enum handling; source text does not imply `SOURCE_BACKED`; activation rejected without verified evidence/location/revision/applicability/unit; prototype origin rejected |
| Lifecycle/versioning | valid/invalid transitions, immutable sealed revision, monotonic revision/supersession, as-of effective lookup, no historical effective-date rewrite |
| Applicability | material/stack/machine/equipment/category/context combinations; missing context vs not applicable; U-007 `PARAMETER` and U-016 `MATERIAL`; unresolved discovery before active filter |
| Unit handling | exact unit, supported conversion trace, missing unit, unsupported unit, dimension mismatch, conversion failure, rounding/catalog version |
| Evaluation | only applicable active source-backed verified rule can PASS/FAIL; proposed/unresolved/inactive/superseded/no rule/missing data/invalid data/conflict behaviors; immutable result/hash |
| Conflict | complete approved resolution, unresolved same-priority/multi-source, missing policy, candidate retention; never call prototype winner |
| MRC aggregation | all five final states; six READY prerequisites; every mixed-state precedence combination; secondary blocker retention; `DATA_INSUFFICIENT` is not final state |
| DWP revision | draft edit, ETag conflict, seal/hash, sealed write rejection, supersession, broken reference, independent orthogonal states |
| Truth/disposition | review/approval/concession records never mutate rule/MRC/quality truth; lifecycle labels never imply success |
| Audit/versioning | stable canonical hash, actor/reason/correlation/software metadata, audit failure rollback, before/after or hash policy |

### 13.3 Integration matrix

- Registry identity/revision/evidence → applicability → immutable evaluation.
- Registry evaluation → MRC check result → deterministic decision.
- MRC immutable decision → DWP exact reference without recalculation.
- Registry evaluation references → DWP compliance display without recalculation.
- Existing Project/WeldPoint/TestResult identity → DWP snapshot/reference while preserving legacy record limitations.
- JWT permission + resource scope + delegated authority + separation-of-duties checks.
- Governed write and audit transaction rollback under injected audit failure.
- Rule/MRC/DWP revision reconstruction after current records change.
- Alembic empty upgrade, prior-head upgrade, downgrade/forward-fix procedure, ORM/migration drift.
- Duplicate idempotency request and competing draft ETags.

### 13.4 Mandatory negative matrix

- zero applicable validated rules → `NOT_EVALUATED`, never READY;
- required applicable unresolved rule → engineering review, never PASS/READY;
- missing required measurement → `DATA_INSUFFICIENT` → manual review;
- invalid/non-finite/stale measurement → manual review and no comparison;
- missing/unsupported/incompatible unit → manual review and no silent conversion;
- required applicable source-backed FAIL → `NOT_READY`, with secondary blockers retained;
- conflicting rules without fully resolving approved policy → engineering review;
- inactive/stale/superseded rule cannot support a new result;
- required evidence unavailable/unverified cannot support PASS/FAIL;
- Registry/audit/persistence/reference unavailable → no authoritative publication;
- unauthorized or out-of-scope review/activation/approval/release → unchanged state plus security audit where required;
- stale ETag/duplicate conflicting idempotency key → no silent overwrite;
- DWP with non-READY MRC, unresolved compliance, insufficient quality, broken reference, or missing required section → release blocked;
- model/AI result, quality test name, or caller-supplied status alone cannot produce acceptance/release.

### 13.5 Regression and E2E

Regression:

- Existing APIs do not gain new READY/PASS/release behavior.
- Current prototype/default rules remain only on the legacy path and never appear as governed active/source-backed rows.
- No governed module imports or automatically calls `DEFAULT_RULES`, `evaluate_compliance`, current priority winner, or other quarantined engineering modules.
- Current 17 tests remain passing unless a separately approved behavior change updates their contract.

E2E scenarios:

1. Empty Registry → explicit `NOT_EVALUATED` evaluation/MRC path → DWP preserves it → release blocked.
2. Required unresolved MRC requirement → `ENGINEERING_REVIEW_REQUIRED` → DWP preserves exact blocker → release blocked.
3. Complete rule but missing required observation → `DATA_INSUFFICIENT` / `MANUAL_REVIEW_REQUIRED` → DWP preserves blocker.
4. Synthetic source-backed fixture in isolated tests → deterministic PASS and FAIL paths; fixture is visibly non-production and cannot seed deployment data.
5. Manual/engineering review appended → deterministic truth unchanged → reevaluation creates new immutable result/assessment/revision.
6. DWP draft → seal → approve (only when test policy permits) → attempted patch rejected → new superseding revision retains history.
7. Audit failure during activation/evaluation/MRC finalization/DWP release → transaction rollback and no success response.
8. Historical reproduction after newer rule, MRC, DWP, project, or model records exist → original hashes/results remain unchanged.

## 14. Safe-to-implement-now matrix

### 14.1 SAFE TO IMPLEMENT NOW

These items contain no engineering thresholds and do not enable production authority by themselves:

- exact enums, orthogonal state fields, evidence/lifecycle types, reason-code catalogs, blocker lists, and the READY prerequisite matrix;
- stable identities, immutable revision/result IDs, content/hash metadata, supersession links, effective/as-of query structures, and retention/tombstone contracts;
- empty Registry identity/revision persistence with no production rules seeded;
- controlled evidence-reference and applicability structures without claims of evidence validity;
- threshold-free rule applicability/evaluation interfaces and explicit unresolved/not-evaluated/data/conflict outcomes;
- unit/dimension catalog interfaces, conversion trace envelopes, and unsupported/mismatch handling using synthetic fixtures only;
- immutable evaluation, candidate/input/conflict trace persistence;
- MRC check-definition, assessment, observation, check-result, review, decision, and historical-reference structures;
- threshold-free representation of exactly U-001–U-016 as unresolved requirements;
- deterministic MRC aggregation implementation and exhaustive tests, because it uses states rather than real thresholds;
- DWP stable identity, draft/seal/supersede mechanics, orthogonal statuses, snapshots, immutable reference envelopes, ETags, hashes, and derived completeness;
- separate review, approval, release-event, and workflow-disposition representations, with actual release kept unavailable until gates pass;
- governed audit schema, caller-owned atomic transaction behavior, correlation/idempotency records, authorization hooks, and structured errors;
- Registry/MRC/DWP read/contracts that explicitly expose unresolved, insufficient, not-evaluated, conflict, and review states;
- synthetic unit, integration, negative, migration, concurrency, and historical-reproduction tests;
- quarantine/import-boundary controls and regression tests protecting current APIs from unsafe new behavior.

### 14.2 BLOCKED UNTIL ENGINEERING EVIDENCE EXISTS

- Any numeric, Boolean, categorical, or qualitative PASS/FAIL criterion for U-001 through U-016.
- Promotion of any current prototype/default value or source claim to `SOURCE_BACKED`.
- Production PASS/FAIL for a currently unresolved MRC requirement.
- Automatic production READY where any required applicable inventory item remains unresolved.
- Source-backed weld/quality acceptance criteria that are not linked to a controlled, applicable evidence revision.
- Automatic compliance, validation, approval, or release based on absent/unverified engineering rules.
- New engineering thresholds for cooling, current, force, material alignment, electrodes, maintenance, water chemistry, pressure, geometry, cables, transformer condition, or any other topic.
- Closed-loop parameter control or automatic production decisions based on unsupported rules/models.

### 14.3 BLOCKED BY NON-EVIDENCE PRODUCTION GATES

Even after engineering evidence exists, production activation remains blocked until atomic audit, identifier/retention/hash policy, master-data/reference ownership, unit/conversion policy, conflict policy, granular RBAC/scope, delegated authority, separation of duties, quality/recipe/equipment ownership, operational monitoring/recovery, PostgreSQL migration validation, and E2E/release review are complete. Concession-based release remains blocked until a separately approved governance policy exists.

## 15. File and module impact map

The paths below are the likely implementation shape following current repository conventions. They are planning targets, not files created by this document.

### 15.1 Files/modules to ADD

Domain, kept infrastructure-independent:

```text
backend/app/domain/governance_types.py
backend/app/domain/rule_registry_types.py
backend/app/domain/rule_applicability.py
backend/app/domain/rule_evaluation.py
backend/app/domain/unit_policy.py
backend/app/domain/readiness.py
backend/app/domain/dwp_revision_policy.py
```

Persistence models:

```text
backend/app/models/governance.py
backend/app/models/rule_registry.py
backend/app/models/mrc.py
backend/app/models/dwp.py
```

Repository adapters:

```text
backend/app/repositories/governance_repository.py
backend/app/repositories/rule_registry_repository.py
backend/app/repositories/rule_evaluation_repository.py
backend/app/repositories/mrc_repository.py
backend/app/repositories/dwp_repository.py
```

Application services:

```text
backend/app/application/governed_audit_service.py
backend/app/application/rule_registry_service.py
backend/app/application/rule_evidence_service.py
backend/app/application/rule_applicability_service.py
backend/app/application/rule_evaluation_service.py
backend/app/application/machine_observation_service.py
backend/app/application/machine_readiness_service.py
backend/app/application/mrc_review_service.py
backend/app/application/dwp_revision_service.py
backend/app/application/digital_weld_passport_service.py
```

API schemas and routes:

```text
backend/app/schemas/governance.py
backend/app/schemas/rule_registry.py
backend/app/schemas/rule_evaluation.py
backend/app/schemas/mrc.py
backend/app/schemas/dwp.py
backend/app/api/v1/rule_registry.py
backend/app/api/v1/rule_evaluations.py
backend/app/api/v1/mrc.py
backend/app/api/v1/dwp.py
```

Tests, retaining the current flat test convention:

```text
backend/tests/test_governance_types.py
backend/tests/test_registry_persistence.py
backend/tests/test_rule_registry.py
backend/tests/test_rule_evaluation.py
backend/tests/test_mrc.py
backend/tests/test_dwp.py
backend/tests/test_governed_audit.py
backend/tests/test_registry_mrc_dwp_integration.py
backend/tests/test_governance_rbac.py
backend/tests/test_migrations.py
backend/tests/test_historical_reproducibility.py
```

Future migration names, following the current manual numbering, are conceptually:

```text
backend/alembic/versions/0003_registry_foundation.py
backend/alembic/versions/0004_registry_evidence_applicability.py
backend/alembic/versions/0005_rule_evaluations.py
backend/alembic/versions/0006_mrc_definitions.py
backend/alembic/versions/0007_mrc_assessments.py
backend/alembic/versions/0008_dwp_identity_revisions.py
backend/alembic/versions/0009_dwp_evidence_governance.py
backend/alembic/versions/0010_governance_hardening.py
```

The actual Alembic revision IDs/names must be generated from the then-current head; do not assume these placeholders if the migration chain changes.

### 15.2 Files/modules to EXTEND

```text
backend/app/models/__init__.py                 export new model metadata
backend/app/main.py                            register reviewed routers only when rollout gates pass
backend/app/api/dependencies.py                granular permission/scope/authority dependencies
backend/app/db/session.py                      only if a unit-of-work/transaction dependency is approved
backend/alembic/env.py                         model discovery and migration checks if required
backend/tests/conftest.py                      synthetic users/roles and DB fixtures; add separate PostgreSQL path
.github/workflows/ci.yml                       migration, PostgreSQL, architecture, and negative-path gates
```

Potential reference adapters may be added around `Project`, `WeldPoint`, and `TestResult`; avoid expanding their current mutable semantics into DWP truth.

### 15.3 Prototype areas to QUARANTINE

```text
backend/app/domain/rules_engine.py
backend/app/domain/engine.py
backend/app/domain/materials.py
backend/app/domain/models.py
backend/app/domain/model_registry.py
backend/app/domain/model4_full.json
backend/app/domain/doe_optimizer.py
backend/app/domain/ensemble.py
backend/app/domain/polynomial_model.py
backend/app/domain/model_validation.py
backend/app/domain/electrode_life.py
backend/app/domain/weld_lobe.py
backend/app/domain/pulse_strategy.py
backend/app/domain/dynamic_resistance.py
backend/app/domain/sensitivity.py
backend/app/domain/energy.py
backend/app/domain/failure_probability.py
backend/app/application/weld_analysis_service.py
backend/app/application/engineering_service.py
backend/app/application/optimization_service.py
backend/app/application/failure_probability_service.py
backend/app/api/v1/weld_analysis.py
backend/app/api/v1/engineering.py
backend/app/api/v1/optimization.py
backend/app/api/v1/failure_probability.py
```

Quarantine means no new governed Registry/MRC/DWP module imports these as engineering authority. It does not authorize modifying or deleting them in this plan.

### 15.4 Areas to leave untouched during the foundational phases

- `frontend/` until reviewed API/state contracts and authorization behavior stabilize.
- Existing migrations `0001_initial.py` and `0002_auth_audit.py`; add forward migrations instead of rewriting history.
- Existing legacy endpoint behavior, tests, and analysis JSON until a separate compatibility/deprecation task is approved.
- `backend/app/application/audit_service.py` and its current callers during foundational work; leave the separately committing legacy helper unchanged, while every new governed path uses `governed_audit_service.py` inside the caller-owned transaction.
- Documentation 111–113 semantics and the 16-item inventory.
- Root `100_SDS_MASTER_INDEX.md` unless documentation governance separately requests indexing document 114.

## 16. Phased delivery plan

### Phase 0 — Implementation baseline and architecture freeze

**Entry:** documents 111–114 available; repository clean scope identified.  
**Scope:** record current branch/SHA/test/migration baseline; reconcile design-status metadata with responsible human approval; freeze subsystem ownership and state semantics; decide identifiers, hashes/canonicalization, transaction/unit-of-work, retention/deletion, reference/snapshot, unit catalog, error, idempotency/ETag, resource scope, authority, and feature-release policies.  
**Deliverables:** signed decision record, module/ownership map, prototype quarantine list, approved migration strategy, approved permission matrix draft, test environments including PostgreSQL, traceability from design acceptance criteria to tests.  
**Tests/checks:** current 17 tests and frontend build in the implementation branch; Alembic current-head smoke check; ORM/migration drift audit; no code change in the planning task.  
**Exit gate:** architecture/security/data owners approve the frozen baseline and no unresolved schema-changing decision blocks Phase 1.  
**Blockers:** document approval ambiguity, identifier/hash/retention/transaction decisions, or unowned master/reference data.

### Phase 1 — Registry persistence foundation

**Entry:** Phase 0 exit; PostgreSQL test environment and migration review process available.  
**Scope:** threshold-free shared governance types, governed audit-compatible metadata, Registry stable identity/revisions, evidence/reference and applicability persistence, lifecycle constraints, repositories, no public activation/evaluation behavior.  
**Deliverables:** additive migrations, ORM models, repository tests, immutable revision/history reads, no seeded rules.  
**Tests:** empty/prior-head Alembic upgrade, PostgreSQL constraints, uniqueness, immutable seal/supersession, no cascade loss, no prototype import/seed, migration/metadata alignment.  
**Exit gate:** persistence can store and reproduce an empty/draft/unresolved revision graph; all governed fields have audit/version ownership.  
**Blockers:** migration/retention/hash decisions, atomic-audit foundation, or any proposed prototype seed.

### Phase 2 — Rule evaluation foundation

**Entry:** Phase 1 exit; evidence, applicability, unit, conflict, and error contracts approved.  
**Scope:** pure applicability/unit/conflict/evaluation policies; immutable evaluation persistence; service/repository orchestration; threshold-free/synthetic fixtures only; no current API behavior change.  
**Deliverables:** deterministic result/reason contracts, as-of selection, candidate/exclusion/conflict/unit trace, idempotent publication, history read.  
**Tests:** exhaustive evidence/lifecycle/applicability/unit/missing/conflict/superseded cases; only synthetic active/source-backed PASS/FAIL fixtures; audit rollback and reproducibility.  
**Exit gate:** evaluator cannot PASS/FAIL without all eligibility requirements and cannot import prototype rules.  
**Blockers:** unapproved conflict/unit policies, atomic audit, incomplete reason codes, or prototype coupling.

### Phase 3 — MRC architecture

**Entry:** Phase 2 exit; document 112 contracts frozen; check-definition/inventory representation approved.  
**Scope:** definitions, exact 16 unresolved records, assessments, observations, Registry orchestration, check results, exact aggregation, reviews, audit, historical reads.  
**Deliverables:** threshold-free MRC services/persistence; all five states; six-prerequisite matrix; all blocker traces; no production READY enablement based on unresolved items.  
**Tests:** aggregation truth table, U-001–U-016 preservation/categories, unresolved/data/no-rule/failure/conflict/manual paths, audit failure, idempotency, reevaluation revision.  
**Exit gate:** architecture handles every non-ready state and can produce READY only in isolated synthetic source-backed cases satisfying all six prerequisites.  
**Blockers:** Registry/evaluation instability, observation/master-context decisions, review authority, or inventory drift.

### Phase 4 — DWP architecture

**Entry:** Phase 3 immutable MRC reference contract; DWP identity/snapshot/reference decisions approved.  
**Scope:** passport identity, draft/immutable revision mechanics, snapshots, recipe/MRC/Registry/quality/model/actual references, completeness, statuses, reviews/approvals as non-release workflow, history/report source boundary.  
**Deliverables:** DWP persistence/services without duplicated calculations; sealed revision/hash/ETag; broken-reference and non-ready preservation; release command unavailable or hard-disabled.  
**Tests:** immutability, supersession, reference pinning, orthogonal states, incomplete/broken/non-ready paths, model advisory boundary, report source revision.  
**Exit gate:** a DWP revision can be reconstructed without mutable current lookup and cannot alter upstream truth.  
**Blockers:** weld identity uniqueness, recipe/equipment/material ownership, retention/object storage, quality criteria, or reference integrity.

### Phase 5 — API, RBAC, and audit integration

**Entry:** domain/application/persistence contracts stable; permission and structured-error policies approved.  
**Scope:** phased routers/schemas, granular permissions/scope/authority, idempotency/ETags, review queues, audit/history APIs, atomic publication, no frontend readiness logic.  
**Deliverables:** OpenAPI contracts; denial behavior; service identities; separation-of-duties checks; outbox/operational event strategy where required.  
**Tests:** endpoint schema/error/idempotency/concurrency; full permission/scope matrix; wildcard-admin engineering-authority denial; audit rollback; GET no-recompute.  
**Exit gate:** no endpoint bypasses service invariants, authorization, scope, or atomic audit.  
**Blockers:** role/authority/scope policy, evidence visibility, audit integrity, monitoring/recovery decisions.

### Phase 6 — Cross-system E2E validation

**Entry:** Phases 1–5 complete in a non-production environment.  
**Scope:** Registry → evaluation → MRC → DWP flows; legacy isolation; PostgreSQL migrations/transactions; failure injection; historical reproduction; external reference stubs.  
**Deliverables:** traceable E2E evidence, performance/concurrency baseline, recovery/runbook, compatibility report, unresolved-path demo.  
**Tests:** all Section 13 E2E/negative scenarios, retry/idempotency, competing revisions, unavailable dependencies, audit/reference repair, migration rollback/forward-fix.  
**Exit gate:** every safety invariant has passing automated evidence and no prototype value reaches the governed path.  
**Blockers:** missing cross-service environment, flaky nondeterminism, unresolved security/audit defects, or historical mismatch.

### Phase 7 — Engineering-evidence enablement

**Entry:** architecture/E2E gates pass; controlled engineering evidence and delegated reviewers available.  
**Scope:** intake and independently review evidence; create new Registry revisions; validate applicability/units/conflict policy; activate only qualifying rules; run controlled MRC/DWP qualification.  
**Deliverables:** evidence dossiers, approval/audit records, qualified rule versions, field-validation evidence where required, deployment-specific applicability and release-policy configuration.  
**Tests:** evidence trace, independent review, source location/hash, rule-by-rule PASS/FAIL validation, comparison to approved engineering examples, no extrapolation.  
**Exit gate:** each enabled production rule has complete qualifying evidence and acceptance approval; unresolved items remain explicitly unresolved.  
**Blockers:** each required/applicable unresolved MRC item blocks engineering enablement for its exact deployment context until resolved. Items proven not applicable to that scope remain unresolved without being silently omitted. Additional blockers include quality criteria, OEM/customer applicability, or insufficient validation data.

### Phase 8 — Production readiness review

**Entry:** Phase 6 passes and required Phase 7 evidence exists for the intended deployment scope.  
**Scope:** security, authorization, separation, audit integrity, retention/legal hold, backup/recovery, performance, monitoring, incident response, migration/runbook, release policy, rollback/forward-fix, operator training, and final traceability review.  
**Deliverables:** production-readiness dossier, signed GO/NO-GO per gate, deployment/rollback/runbooks, support ownership, release artifact provenance.  
**Tests:** production-like E2E, security/permission review, disaster recovery, audit-integrity verification, load/concurrency, migration rehearsal, historical reconstruction, fail-closed dependency outages.  
**Exit gate:** every Section 18 production gate is GO for the exact deployment scope.  
**Blockers:** any evidence, RBAC, audit, retention, reference, quality, MRC, DWP, security, operational, or E2E NO-GO.

## 17. Exactly one first coding task

### Task name

**Empty Engineering Registry Revision Persistence Foundation**

### Exact scope

After Phase 0 approval, add threshold-free shared governance/evidence/lifecycle types and persistence for:

- a stable `EngineeringRule` identity;
- immutable `EngineeringRuleRevision` metadata and supersession links;
- evidence-class/lifecycle enums and content/hash/audit-compatible metadata;
- the append-only `GovernedAuditEvent` persistence shape needed by later caller-owned atomic publication, without adding a writer service or endpoint;
- a minimal `RuleRegistryRepository` for create/read/history operations under a caller-owned transaction, with no internal commit;
- an additive Alembic migration that creates empty tables only;
- persistence and migration tests.

The task creates no service, API, evaluator, MRC, DWP, activation command, production seed, or change to legacy analysis behavior.

### Expected files

```text
ADD     backend/app/domain/governance_types.py
ADD     backend/app/domain/rule_registry_types.py
ADD     backend/app/models/governance.py
ADD     backend/app/models/rule_registry.py
EXTEND  backend/app/models/__init__.py
ADD     backend/app/repositories/rule_registry_repository.py
ADD     backend/alembic/versions/0003_registry_foundation.py
ADD     backend/tests/test_registry_persistence.py
ADD     backend/tests/test_migrations.py
```

`0003_registry_foundation.py` is the expected planning name; use the actual next Alembic revision identifier at implementation time.

### Tests

- clean Alembic upgrade reaches the new head on PostgreSQL and disposable SQLite where supported;
- upgrade from current `0002_auth_audit` preserves all existing data;
- no Registry rows are seeded;
- stable rule ID and revision uniqueness constraints work;
- sealed revision identity/content hash and supersession fields cannot be destructively rewritten through the repository contract;
- governed audit records require durable event/entity/action/actor/correlation/version metadata and are append-only through the persistence contract;
- lifecycle/evidence enums reject unknown values;
- unresolved/draft fixture contains no threshold/formula and cannot claim active source-backed authority;
- current 17 backend tests remain passing;
- current API/OpenAPI behavior is unchanged.

### Definition of done

1. Phase 0 schema/identifier/hash/retention decisions are recorded.
2. The new Registry/governance migration and its new ORM metadata agree and pass PostgreSQL review. Pre-existing 0001/0002-versus-legacy-model drift is explicitly documented in a reviewed baseline allowlist and handled by a separate forward-fix decision; this task does not silently alter legacy indexes.
3. Tables are empty after migration and no prototype module is imported.
4. Models represent stable identity and immutable revisions without adding engineering values.
5. Tests prove uniqueness, history/supersession shape, empty seed, and compatibility.
6. No router/service calls the new persistence, so current production behavior is unchanged.
7. Review explicitly confirms this task does not authorize activation, PASS/FAIL, READY, DWP release, or evidence promotion.

### Explicitly out of scope

- evidence-document upload/verification workflow;
- rule applicability/evaluation and unit conversion;
- copying `DEFAULT_RULES` or any hard-coded value;
- Registry APIs or frontend;
- MRC or DWP entities/services;
- altering legacy `rules_engine.py`, analysis output, or tests;
- production activation, deployment, staging, commit, or release.

## 18. GO / NO-GO gates

| Gate | GO criteria | Current assessment |
|---|---|---|
| Registry persistence | Phase 0 decisions approved; empty additive migration; immutable revisions/evidence links; no prototype seed; audit-compatible transaction design; migration/PostgreSQL tests pass | **GO for threshold-free implementation after Phase 0; NO-GO for production authority today** |
| Rule evaluation | Pure deterministic policy; eligibility/evidence/applicability/unit/conflict contracts approved; immutable/audited publication; exhaustive negative tests; no prototype import | **GO for threshold-free/synthetic implementation after Registry; NO-GO for production PASS/FAIL today** |
| MRC architecture | Registry/evaluator available; exact states, precedence, six prerequisites, 16 inventory, observations/reviews/history tested; no duplicated thresholds | **GO for threshold-free implementation after evaluation foundation** |
| MRC engineering enablement | Required deployment rules individually promoted with qualifying evidence; applicability and inputs available; conflict/unit policies approved; field validation complete | **NO-GO — current inventory is 0 source-backed / 16 unresolved** |
| DWP architecture | MRC/Registry immutable reference contracts stable; identity/snapshot/reference/revision/retention decisions approved; no recalculation; history tests pass | **GO for threshold-free implementation after MRC contracts** |
| DWP production release | Exact qualifying MRC, Registry/quality/recipe/equipment references; approved release policy; approval separation; retention/object/audit integrity; negative and E2E gates pass | **NO-GO** |
| RBAC | Granular permissions, resource scopes, delegated authority, service identity, separation of duties, deny/default and evidence/audit visibility approved and tested | **NO-GO until policy and implementation are complete** |
| Audit | Governed writer joins caller transaction; required metadata/hashes/correlation/software versions; append-only integrity; failure rollback; query/retention/access controls pass | **NO-GO until atomic governed audit exists** |
| E2E | Registry→evaluation→MRC→DWP positive/negative/history flows pass on PostgreSQL; dependency/audit failures fail closed; legacy isolation proven | **NO-GO until Phases 1–6 are implemented and verified** |
| Production release | All preceding gates GO for exact scope; source evidence/quality/release policies approved; security/operations/recovery/performance/migration review signed | **NO-GO** |

A gate is deployment-scope-specific. Passing threshold-free architecture gates does not imply passing engineering enablement or production release.

## 19. Final readiness assessment

### A. Registry architecture implementation-ready?

**Yes, for threshold-free implementation after Phase 0.** The identity, revision, evidence, lifecycle, applicability, persistence, audit, and API boundaries are sufficiently defined. No production Registry implementation exists yet, and no current rule is promoted by this assessment.

### B. Rule evaluation architecture implementation-ready?

**Yes, for a threshold-free evaluator and synthetic tests after Registry persistence.** Production PASS/FAIL remains blocked until applicable rules are active, source-backed, verified, unit-safe, and conflict-resolved.

### C. MRC architecture implementation-ready?

**Yes, for threshold-free scaffolding and all unresolved/manual/not-evaluated paths.** Its five states, six READY prerequisites, precedence, ownership, observation/review model, audit, and historical behavior are defined.

### D. MRC engineering-rule-ready?

**No.** The authoritative MRC inventory remains exactly 16 unresolved items: `SOURCE_BACKED=0`, `PROPOSED=0`, `UNRESOLVED=16`.

### E. DWP architecture implementation-ready?

**Yes, for stable identity, immutable revision, snapshot/reference, status, audit, and non-release workflow foundations.** It must consume, not duplicate, Registry and MRC truth.

### F. DWP production-release-ready?

**No.** Registry/MRC engineering evidence, source-backed quality criteria, recipe/equipment/master ownership, granular authority, separation of duties, retention, atomic audit, external-reference storage, E2E, and release policy are incomplete.

### G. What can safely start now?

Phase 0 decisions/architecture freeze, followed by the single first coding task in Section 17. After its gate passes, the remaining safe-now items in Section 14.1 can proceed in dependency order without engineering thresholds or production behavior changes.

### H. What is blocked by the 16 unresolved MRC items?

They block using those requirements for production PASS/FAIL, automatic MRC READY where required/applicable, MRC-backed DWP production release, source-backed compliance claims, and automatic control/release based on them. They do not block empty Registry persistence, immutable evidence/version/reference structures, rule-result contracts, unresolved/data/review behavior, MRC/DWP architecture, audit/RBAC hooks, or synthetic tests.

## 20. Final conclusion

This plan is repository-grounded, preserves documents 111–113, introduces no engineering values, changes no evidence classification, and keeps all existing prototype/default logic outside the governed authority path. It defines a safe implementation sequence with independent architecture, engineering-evidence, authorization, audit, E2E, and production-release gates. Planning is complete; implementation has not started.

IMPLEMENTATION PLAN GO
