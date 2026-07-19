# Architecture Decisions and Boundaries

## ADR-001 — Independent product boundary

Decision: Spot Welding Parameter Assistance remains a separate product.

Excluded technologies and functions:
- image processing
- camera inspection
- OpenCV
- YOLO/CNN/ResNet
- weld image classification

Reason: customer, scope, pricing, data flow, verification method and software architecture differ from Spot Welding Image Processing.

## ADR-002 — Domain core is infrastructure-independent

Decision: domain modules may not depend on FastAPI, SQLAlchemy sessions, environment variables or deployment tools.

Reason: calculation engines must be testable, portable and deterministic.

## ADR-003 — Configuration validation occurs at startup

Decision: environment access and required-setting validation belong to typed configuration/startup logic, not module import.

Reason: import-time failures make tests, tooling and deployment brittle.

## ADR-004 — Rule sources use providers

Decision: norm and OEM sources are integrated through providers registered in a rule registry.

Reason: new standards must be added without modifying the central evaluator.

## ADR-005 — Engineering models are versioned assets

Decision: every model is registered with units, validity range, provenance, lifecycle state and verification evidence.

Reason: engineering results must remain reproducible and auditable.

## ADR-006 — Production frontend is statically served

Decision: development servers are not used for production deployment.

Reason: production needs deterministic builds, controlled headers and scalable serving.

## ADR-007 — CI is a release gate

Decision: tests, lint, type checks, migration checks, frontend build and smoke validation must pass before merge/release.

Reason: local success alone is insufficient.

## ADR-008 — Recommendations remain explainable

Decision: recommendations must include dominant factors, expected effect, constraints, warnings, model/rule versions and applicability limits.

Reason: the product is engineering decision support, not an opaque prediction tool.

## ADR-009 — Standards data is traceable

Decision: no rule may be presented as normative without source, revision, applicability and validation status.

Reason: unverified or copyrighted standard content must not be represented as authoritative implementation.

## ADR-010 — No silent extrapolation

Decision: model execution outside the verified input domain must warn, reject or explicitly mark extrapolation.

Reason: numerical output without applicability control is unsafe.
