# Changelog

## [3.0.0-alpha.3] - 2026-09-04

### Added
- Phase 6A1: real-PostgreSQL CI/test foundation for governed E2E
  (Alembic identifier-length, URL-interpolation, and revision-capacity
  compatibility; CI JWT environment and CI health checks).
- Phase 6A2: governed PostgreSQL happy-path E2E covering the full
  identity → draft → source-backed → verified evidence → SOURCE_BACKED
  enablement → activation → evaluation → machine readiness → digital
  weld passport chain.
- Phase 6A2: canonical-scope repair for lifecycle audit metadata
  (lifecycle authority scope now uses the canonical 4-dimension
  `VerificationScopeSnapshot` snapshot, structurally identical to the
  verified evidence decision's `resource_scope`).
- Phase 6A3: lifecycle negative-path E2E coverage
  (`SEPARATION_OF_DUTIES_VIOLATION`, `MISSING_SCOPE_SNAPSHOT`,
  `UNRESOLVED_BASIS` via scope-mismatch, missing-verified-decision,
  and missing-evidence-references branches).
- Phase 6A4: evidence-verification negative-path E2E coverage
  (`MISSING_EVIDENCE_REFERENCE`, `MISSING_DURABLE_HUMAN_VERIFIER`,
  `MISSING_SUBMITTER_IDENTITY`, `SEPARATION_OF_DUTIES_VIOLATION`,
  `NO_MATCHING_DELEGATION`, `DELEGATION_REVOKED`, `DELEGATION_EXPIRED`,
  `DELEGATION_NOT_YET_EFFECTIVE`, `SCOPE_MISMATCH`,
  `REVOCATION_METADATA_INCOMPLETE`) plus idempotency
  `CONFLICT` coverage (same key + different request hash must fail
  closed without writing a second receipt or audit event).

### Changed
- Lifecycle audit `authority_scope` now flows through the canonical
  4-dimension snapshot shape (Phase 6A2 repair) to match the verified
  evidence decision's `resource_scope` exactly.

### Validation
- Phase 6A1: PostgreSQL foundation test fixture and CI health checks
  established.
- Phase 6A2: full real-PostgreSQL happy-path E2E passes end-to-end
  (identity → DWP).
- Phase 6A3: 5 lifecycle denial-path assertions pass under real
  PostgreSQL.
- Phase 6A4: 10 evidence-verification denial-path assertions plus
  1 idempotency `CONFLICT` assertion pass under real PostgreSQL.
- CI: PostgreSQL E2E runs on every push; local PostgreSQL remains
  CI-only (the `tests_postgresql` conftest refuses to run without
  `POSTGRES_TEST_DATABASE_URL`; no SQLite fallback).

### Governance
- All Phase 6A denial tests assert a deterministic
  `GovernedAuditEvent` with `entity_type=evidence_verification_denial`
  or `engineering_rule_lifecycle_denial` and the exact denial code
  (no authority is silently granted on omission or mismatch).
- Separation of duties remains mandatory at the lifecycle layer
  (submitter must not enable/activate).
- Canonical-scope equality is now a hard precondition at the lifecycle
  layer (audit `authority_scope` must equal the verified evidence
  decision's `resource_scope`; the legacy short project-only scope is
  no longer accepted by the lifecycle code).
- Idempotency `CONFLICT` raises `ValueError` and does not silently
  re-evaluate.
- No application code, no migration, no schema, and no engineering
  threshold values were introduced or modified by Phase 6A1–6A4.

### Known Limitations
- `EVIDENCE_VERIFICATION_AUTHORITY_FOUNDATION` remains
  `BLOCKED` per SDS-115 §22 (the foundation is now covered by
  regression tests but is not yet declared production-enabled).
- `SOURCE_BACKED_PROMOTION`, `RULE_ENABLEMENT`, `RULE_ACTIVATION`,
  `GOVERNED_APPLICABILITY`, and `RULE_EVALUATION_PERSISTENCE` remain
  `DEFERRED` per SDS-115 §22.
- `MIGRATION_0006_ALLOWED = NO` per SDS-115 §22. Migration 0006 is
  present in the repository but the runtime foundation is not
  declared production-enabled.
- `IMPLEMENTATION_UNLOCKED = NO` per SDS-115 §22.
- `INVALID_CAPABILITY` defensive branch in
  `EvidenceVerificationService` is unreachable through the production
  repository invariant (the repository refuses to insert
  non-`EVIDENCE_VERIFICATION` delegations) and is therefore not
  covered by a negative-path test; the branch is documented but
  unreachable from the production code path.

### Scope
This is an **alpha prerelease** that consolidates the Phase 6A
governance validation milestone. It strengthens governed verification
and lifecycle validation through real-PostgreSQL E2E coverage; it
does **not** declare production readiness, does not enable
`SOURCE_BACKED_PROMOTION` / `RULE_ENABLEMENT` / `RULE_ACTIVATION`,
does not unlock migration 0006, and does not introduce any
engineering threshold values.

## [3.0.0-alpha.2] - 2026-09-01

### Added
- Governed Evidence Verification API.
- Governed Engineering Rule Registry lifecycle API.
- Governed Rule Evaluation API.
- Governed Machine Readiness API.
- Governed Digital Weld Passport Draft and Lifecycle API.

### Governance
- Authenticated user identity is the authoritative API actor identity.
- System Admin wildcard access does not grant governed engineering authority.
- Exact revision/provenance pinning is preserved.
- Governed writes, audit events, and idempotency receipts remain atomic.
- No authoritative latest/current rule, evaluation, MRC, or DWP lookup.
- GET/read operations do not recompute engineering truth.
- DWP finalization retains READY gate and separation-of-duties controls.

### Validation
- Full backend regression suite: **361 passed**.
- Phase 5 governed API targeted Ruff checks: **PASS**.

### Scope
This is an **alpha prerelease**.
Phase 6 — Cross-system E2E Validation is not included in v3.0.0-alpha.2.


## [1.3.0] - 2026-07-17
- Fixed frontend TypeScript build and API contract drift.
- Stabilized Windows SQLite test teardown.
- Removed fallback JWT secret and default admin bootstrap.
- Enforced Alembic-first container startup.
- CI now requires backend tests and frontend build.


## [1.2.0] - 2026-07-16

### Added
- GitHub-ready repository structure.
- Filled architecture, requirements, engineering, API, database, security,
  testing, deployment, and roadmap documentation.
- GitHub issue templates and pull-request template.
- CI workflow for backend tests and frontend build.
- Environment example and repository governance files.

### Changed
- Product scope clarified: this repository contains parameter analysis only.
- Image processing, camera, OpenCV, YOLO, and visual defect classification are
  explicitly excluded and belong to the separate Spot Welding Image Processing product.

## [1.1.0]
- Parameter-based potential failure probability engine.
- Ten potential failure modes with probability, confidence, severity,
  contributors, validation tests, and recommended actions.
- 17 automated backend tests passed.

## [1.0.0]
- FastAPI + React professional architecture.
- Model-4, DOE optimization, ensemble prediction, weld-lobe support,
  authentication, projects, weld points, revisions, approvals, and tests.
