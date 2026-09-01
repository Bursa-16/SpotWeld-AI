# Changelog

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
