# SpotWeld-AI — Spot Welding Parameter Analysis

Professional engineering decision-support software for **resistance spot welding parameter analysis, governed rule evaluation, machine readiness, and Digital Weld Passport traceability**.

> **Product scope:** This repository contains the **Spot Welding Parameter Analysis** product.  
> It does **not** contain image processing, camera inspection, OpenCV, YOLO, or visual defect classification. Those capabilities belong to the separate **Spot Welding Image Processing** product.

---

## Release Status

### v3.0.0-alpha.2 — Governed API Integration

The `v3.0.0-alpha.2` alpha extends the governed backend architecture with the governed API integration layer for deterministic, revision-pinned, auditable, reproducible, and fail-closed engineering decisions.

### Current Verification

- Full backend suite: **361 passed**
- Digital Weld Passport focused tests: **3 passed**
- Migration tests: **11 passed**
- Machine Readiness persistence tests: **8 passed**
- Ruff: **PASS**
- Alembic migration chain: through **`0010_digital_weld_passport`**

This is an **alpha prerelease**. The governed backend foundation is established, while broader API and frontend exposure of the new workflows remains future work.

---

## What's New in v3.0.0-alpha.2

Phase 5 exposes the governed engineering chain through authenticated API boundaries:

- Evidence Verification API
- Engineering Rule Registry lifecycle API (SOURCE_BACKED → ENABLED → ACTIVE)
- Governed Rule Evaluation API
- Machine Readiness API
- Digital Weld Passport Draft and Lifecycle API
- Authenticated actor identity with actor-spoofing prevention
- System Admin wildcard explicitly excluded from governed engineering authority
- Exact revision and provenance pinning
- Persistent command idempotency with replay/conflict/in-progress handling
- Atomic governed state + audit + receipt transactions
- No authoritative latest/current rule, evaluation, MRC, or DWP lookup
- No GET-time recomputation of engineering truth
- READY gate enforcement for DWP finalization
- DWP separation-of-duties enforcement

**Phase 6 — Cross-system E2E Validation is not included in this prerelease.**

---

## Engineering Principles

SpotWeld-AI keeps deterministic engineering logic authoritative.

- No hidden or implicit engineering authority
- No automatically invented engineering thresholds
- Exact revision and provenance pinning
- Fail-closed handling of missing, stale, conflicting, or invalid inputs
- Human-scoped authority
- Separation of duties
- Append-only corrections
- Immutable historical records
- Persistent governed idempotency
- Atomic state + audit + receipt transactions
- No silent “latest revision” authority
- AI may assist with explanation and knowledge workflows but does not override governed deterministic engineering decisions

---

## Governed Engineering Flow

```text
Engineering Rule Registry
        ↓
Evidence + Verification Authority
        ↓
SOURCE_BACKED Promotion
        ↓
ENABLED
        ↓
ACTIVE
        ↓
Deterministic Applicability Resolution
        ↓
Pure Governed Rule Evaluation
        ↓
Persisted Rule Evaluation
        ↓
Machine Readiness Check (MRC)
        ↓
Persisted MRC Assessment
        ↓
Digital Weld Passport (DWP)
```

Each governed stage pins the exact revisions and provenance required to reproduce the engineering decision later.

---

# Core Capabilities

## Spot Welding Engineering

- Material and sheet-stack analysis
- Welding current evaluation
- Weld time evaluation
- Electrode force evaluation
- Squeeze and hold time analysis
- Cooling assessment
- Electrode evaluation
- Nugget diameter estimation
- Weld-lobe analysis
- DOE optimization
- Model-4 support
- Ensemble model support
- Parameter-based potential failure probabilities
- Explanation of dominant factors
- Recommended corrective actions

---

# Engineering Rule Registry

The governed Engineering Rule Registry provides:

- Immutable engineering rule revisions
- Evidence-to-rule traceability
- Explicit `SOURCE_BACKED` classification
- Revision-level provenance
- Append-only lifecycle history
- Governed promotion, enablement, and activation

Governed lifecycle:

```text
DRAFT → SOURCE_BACKED → ENABLED → ACTIVE
```

Important rules:

- `SOURCE_BACKED` does not mean `ENABLED`
- `SOURCE_BACKED` does not mean `ACTIVE`
- No direct `SOURCE_BACKED → ACTIVE` transition
- Activation requires a separate governed transition
- Exact scope and effective-time rules apply
- Legacy `DEFAULT_RULES` / `rules_engine` paths are not promoted into governed authority

---

# Evidence Verification Authority

Evidence verification is governed by explicit human authority.

Capabilities include:

- Human-only authoritative evidence verification
- Explicit scoped delegation
- Exact EvidenceReference revision pinning
- Creator / verifier separation of duties
- No wildcard administrator authority
- No implicit role-based authority
- Immutable authority snapshots
- Append-only verification corrections
- Auditable authorization denials
- Persistent idempotency
- Atomic governed transactions

Evidence verification does **not** automatically promote or activate an engineering rule.

---

# SOURCE_BACKED Promotion

A rule revision may become `SOURCE_BACKED` only through a separate governed transition.

Requirements include:

- Exact rule revision
- Verified evidence
- Exact evidence revision pinning
- Governed promotion authority
- Separation from evidence-verification authority where required
- Audit traceability
- Persistent idempotency
- Atomic Unit of Work

`SOURCE_BACKED` remains distinct from `ENABLED` and `ACTIVE`.

---

# Rule Enablement and Activation

Governed rule lifecycle transitions are explicit and append-only.

```text
SOURCE_BACKED
     ↓
  ENABLED
     ↓
   ACTIVE
```

Controls include:

- Explicit human lifecycle authority
- Exact customer / project / site / machine scope
- Effective-time windows
- Fail-closed lifecycle checks
- No automatic activation
- No direct `SOURCE_BACKED → ACTIVE`
- Historical lifecycle events remain immutable

---

# Governed Applicability Resolution

The applicability resolver determines which `ACTIVE` rule revision governs an explicit engineering context.

Key characteristics:

- Exact customer / project / site / machine context matching
- Explicit scopes only
- No implicit wildcard fallback
- Most-specific governed match precedence
- Equal-specificity conflicts fail closed
- Zero eligible matches return unresolved
- Candidate-order permutation invariance
- Deterministic provenance ordering
- Immutable provenance-complete results

The same candidate set produces the same result regardless of input ordering.

---

# Governed Rule Evaluation

Rule evaluation operates only on the exact rule revision selected by governed applicability resolution.

Supported deterministic operators:

- `MIN`
- `MAX`
- `RANGE`
- `EQUALS`

Supported outcomes:

- `SATISFIED`
- `NOT_SATISFIED`
- `NOT_APPLICABLE`
- `UNIT_MISMATCH`
- `UNRESOLVED`

Unit conversion is permitted only through an explicit governed Unit Policy.

The evaluator does not use:

- implicit unit coercion
- hidden threshold lookup
- invented epsilon/tolerance behavior
- automatic evaluation of unselected rules

Unsupported or malformed inputs fail closed.

---

# Rule Evaluation Persistence

Persisted Rule Evaluations provide:

- Stable evaluation identity
- Append-only evaluation revisions
- Exact rule revision pinning
- Exact applicability-result pinning
- Exact observation snapshot
- Exact unit-policy and conversion provenance
- Immutable result snapshot
- Append-only correction and supersession
- Governed audit
- Persistent idempotency
- Atomic evaluation + audit + receipt completion

The persistence layer **does not recompute** applicability, unit conversion, or engineering comparison.

---

# Machine Readiness Check — MRC

Machine Readiness Check deterministically aggregates governed engineering evaluations.

Supported outcomes:

- `READY`
- `NOT_READY`
- `ENGINEERING_REVIEW_REQUIRED`
- `MANUAL_REVIEW_REQUIRED`
- `NOT_EVALUATED`

MRC includes:

- Governed required / optional check definitions
- Exact RuleEvaluation revision pins
- Deterministic blocker precedence
- Missing evidence handled fail-closed
- Invalidated evidence handled fail-closed
- Secondary blocker trace retention
- Exact context matching
- Permutation-invariant aggregation

The MRC layer does **not** invent engineering requirements or thresholds.

---

# Machine Readiness Persistence

Persisted Machine Readiness Assessments provide:

- Stable `assessment_id`
- Immutable `revision_number`
- Exact RuleEvaluation revision pins
- Immutable blocker snapshots
- Immutable prerequisite snapshots
- Append-only correction history
- Governed audit
- Persistent idempotency
- Atomic transaction handling

The persistence layer does not recompute MRC.

Downstream consumers pin an exact:

```text
assessment_id + revision_number
```

There is no authoritative “latest MRC” lookup.

---

# Digital Weld Passport — DWP

The v3 alpha introduces the governed Digital Weld Passport foundation.

## Passport Identity

- Stable passport identity
- Immutable passport revisions
- Exact weld identity scope
- Exact revision provenance
- Append-only correction and supersession
- No mutable “latest passport” authority

## MRC Integration

DWP pins an exact Machine Readiness Assessment:

```text
assessment_id + revision_number
```

There is no “latest MRC” authority.

A passport may exist as a draft with a non-READY MRC, but final governed states require READY.

## DWP Lifecycle

```text
CREATED
   ↓
DRAFT
   ↓
ENGINEERING_DEFINED
   ↓
VALIDATION_PENDING
   ↓
VALIDATED
   ↓
APPROVED
   ↓
PRODUCTION_ACTIVE
```

Historical dispositions may include:

```text
SUPERSEDED
RETIRED
ARCHIVED
```

## Readiness Gate

- `DRAFT` may exist with a non-READY MRC
- `VALIDATED` requires a pinned `READY` MRC
- `APPROVED` requires a pinned `READY` MRC
- `PRODUCTION_ACTIVE` requires a pinned `READY` MRC

Non-READY states remain explicit blockers and are never coerced to READY.

## Governance

DWP provides:

- Explicit lifecycle transitions
- Illegal lifecycle jumps rejected
- Finalized revisions immutable
- Corrections through new superseding revisions
- Draft editor / engineering approver / production-release separation of duties
- No wildcard authority
- Exact engineering provenance
- Governed audit
- Persistent idempotency
- Caller-owned atomic Unit of Work
- No MRC or rule-evaluation recomputation

---

# Potential Failure Modes

The parameter-analysis engine includes engineering assessment of potential failure modes such as:

- Expulsion / metal splash
- Insufficient fusion
- Small nugget
- Excessive indentation
- Electrode sticking
- Accelerated electrode wear
- LME / surface cracking risk
- Coating damage
- Shunt-related instability
- Cooling-related instability

---

# Architecture

```text
React + TypeScript
        ↓
       REST
        ↓
FastAPI Application API
        ↓
Application Services
        ↓
Governed Engineering Domain
        ↓
┌─────────────────────────────┐
│ Engineering Rule Registry   │
│ Evidence Verification       │
│ Applicability Resolution    │
│ Rule Evaluation             │
│ Machine Readiness           │
│ Digital Weld Passport       │
└─────────────────────────────┘
        ↓
SQLAlchemy / PostgreSQL
```

Governed write operations use caller-owned Unit of Work boundaries.

Authoritative state, governed audit events, and persistent idempotency receipts are committed atomically.

---

# Repository Structure

```text
backend/
  app/
    application/      Governed application services
    domain/           Deterministic engineering domain
    models/           SQLAlchemy persistence models
    repositories/     Persistence repositories

  alembic/
    versions/         Governed database migration chain

  tests/              Backend and governance tests

frontend/              React + TypeScript application

docs/                  Product, architecture, SDS and governance documents

.github/               CI and repository governance

docker-compose.yml     Local multi-service environment
```

---

# Database Evolution

The governed backend migration chain currently extends through:

```text
0010_digital_weld_passport
```

Major governed migration stages include:

- Engineering Rule Registry persistence
- Evidence revision and applicability foundation
- Evidence Verification Authority
- Rule lifecycle events
- Rule Evaluation persistence
- Machine Readiness persistence
- Digital Weld Passport persistence

---

# Governance Documentation

Key governed-engineering documents include:

1. `100_SDS_MASTER_INDEX.md`
2. `docs/111_ENGINEERING_RULE_REGISTRY_DESIGN.md`
3. `docs/112_MACHINE_READINESS_CHECK_DESIGN.md`
4. `docs/113_DIGITAL_WELD_PASSPORT_DESIGN.md`
5. `docs/114_REGISTRY_MRC_DWP_IMPLEMENTATION_PLAN.md`
6. `docs/115_EVIDENCE_VERIFICATION_AUTHORITY_POLICY.md`

`100_SDS_MASTER_INDEX.md` is the authoritative SDS registry.

---

# Quick Start with Docker

```powershell
copy .env.example .env
docker compose up --build
```

Frontend:

```text
http://localhost:5173
```

API:

```text
http://localhost:8000
```

Swagger:

```text
http://localhost:8000/docs
```

---

# Backend Development

```powershell
cd backend
py -m pip install -r requirements.txt
py -m pytest -q
py -m uvicorn app.main:app --reload
```

The `v3.0.0-alpha.1` governed backend release was validated with Python 3.14.6 in the active development environment.

---

# Frontend Development

```powershell
cd frontend
npm install
npm run dev
```

---

# v3.0.0-alpha.1 Scope

Included in this alpha prerelease:

- Governed Engineering Rule Registry
- Evidence revision foundation
- Evidence Verification Authority
- `SOURCE_BACKED` promotion
- Governed Rule Enablement
- Governed Rule Activation
- Deterministic Applicability Resolution
- Pure Governed Rule Evaluation
- Rule Evaluation Persistence
- Pure Machine Readiness Check
- Machine Readiness Persistence
- Digital Weld Passport foundation

Not yet part of the complete governed application workflow:

- Full API exposure of all governed capabilities
- Full frontend integration
- Concession-based production-release workflows
- Automatic machine-release actions
- External system integrations
- Expanded Digital Weld Passport visualization and reporting
- New engineering thresholds

---

# Release

## v3.0.0-alpha.1 — Governed Engineering Foundation

This alpha prerelease establishes the backend architecture for traceable, deterministic, revision-pinned, auditable, and reproducible engineering decisions across the SpotWeld-AI engineering lifecycle.

The architecture deliberately separates:

```text
Evidence
   ↓
Rule Authority
   ↓
Applicability
   ↓
Evaluation
   ↓
Readiness
   ↓
Passport / Traceability
```

Future API, frontend, analytics, automation, and AI capabilities can build on this governed foundation without weakening deterministic engineering authority or traceability.

---

# License

See `LICENSE` for repository licensing terms.
