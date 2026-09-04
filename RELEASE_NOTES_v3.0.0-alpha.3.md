# SpotWeld-AI v3.0.0-alpha.3 — Governed Cross-System E2E Validation

## Overview
This alpha prerelease consolidates the Phase 6A governance validation
milestone on top of the Phase 5 governed API integration. It strengthens
the governed engineering chain with real-PostgreSQL cross-system
end-to-end coverage of both the positive path and the fail-closed
denial surface. This release primarily strengthens governed verification
and lifecycle validation; it does not declare production readiness and
does not introduce any engineering threshold values.

## Included

### Phase 6A1 — Real-PostgreSQL CI/test foundation
- Real-PostgreSQL test fixture (`tests_postgresql/conftest.py`)
- Alembic PostgreSQL identifier-length, URL-interpolation, and
  revision-capacity compatibility fixes
- CI JWT environment and CI health-check fixes
- Local PostgreSQL remains CI-only; no SQLite fallback

### Phase 6A2 — Governed PostgreSQL happy-path E2E
- Full cross-system happy path: identity → draft → source-backed →
  verified evidence → `SOURCE_BACKED` enablement → activation →
  rule evaluation → machine readiness → digital weld passport
- Canonical-scope repair for lifecycle audit metadata
  (`VerificationScopeSnapshot.as_dict()` shape, structurally
  identical to the verified evidence decision's `resource_scope`)

### Phase 6A3 — Lifecycle denial-path E2E
- `SEPARATION_OF_DUTIES_VIOLATION` (submitter must not enable/activate)
- `MISSING_SCOPE_SNAPSHOT` (omission never grants authority)
- `UNRESOLVED_BASIS` via scope-mismatch between audit authority
  scope and verified evidence `resource_scope`
- `UNRESOLVED_BASIS` when the source-backed revision lacks a
  verified evidence decision
- `UNRESOLVED_BASIS` when the source-backed revision has no
  evidence references

### Phase 6A4 — Evidence-verification denial-path E2E
- `MISSING_EVIDENCE_REFERENCE`
- `MISSING_DURABLE_HUMAN_VERIFIER`
- `MISSING_SUBMITTER_IDENTITY`
- `SEPARATION_OF_DUTIES_VIOLATION` (verifier ≠ submitter)
- `NO_MATCHING_DELEGATION`
- `DELEGATION_REVOKED`
- `DELEGATION_EXPIRED`
- `DELEGATION_NOT_YET_EFFECTIVE`
- `SCOPE_MISMATCH` (requested ≠ delegation)
- `REVOCATION_METADATA_INCOMPLETE`
- Idempotency `CONFLICT` (same key + different request hash must
  fail closed by raising `ValueError` without writing a second
  receipt or audit event)

Each negative-path assertion persists a deterministic
`GovernedAuditEvent` with the exact `entity_type`
(`evidence_verification_denial` or
`engineering_rule_lifecycle_denial`) and the exact `denial_code`. No
authority is silently granted on omission or mismatch.

## Validation
- Real-PostgreSQL cross-system E2E (Phases 6A1–6A4) passes in CI.
- Full backend suite: **361 passed** (preserved from v3.0.0-alpha.2)
- Digital Weld Passport focused tests: **3 passed**
- Migration tests: **11 passed**
- Machine Readiness persistence tests: **8 passed**
- Git diff checks: **PASS**
- Local PostgreSQL execution of `tests_postgresql/` remains CI-only
  (the conftest refuses to run without `POSTGRES_TEST_DATABASE_URL`;
  no SQLite fallback is supported)

## Scope
This is an **alpha prerelease**.

Per SDS-115 §22, the following items remain active governance gates
and are explicitly preserved by this release:

- `EVIDENCE_VERIFICATION_AUTHORITY_FOUNDATION = BLOCKED`
  (the foundation is now covered by regression tests but is not yet
  declared production-enabled)
- `SOURCE_BACKED_PROMOTION = DEFERRED`
- `RULE_ENABLEMENT = DEFERRED`
- `RULE_ACTIVATION = DEFERRED`
- `GOVERNED_APPLICABILITY = DEFERRED`
- `RULE_EVALUATION_PERSISTENCE = DEFERRED`
- `MIGRATION_0006_ALLOWED = NO`
- `IMPLEMENTATION_UNLOCKED = NO`

The `INVALID_CAPABILITY` defensive branch in
`EvidenceVerificationService` is unreachable through the production
repository invariant and is therefore not covered by a negative-path
test.

No application code, no migration, no schema, and no engineering
threshold values were introduced or modified by Phase 6A1–6A4.

Phase 7 and later — production enablement of the deferred lifecycle
items, concession-based release workflows, full frontend integration,
and external system integrations — remain future work and are not
part of v3.0.0-alpha.3.
