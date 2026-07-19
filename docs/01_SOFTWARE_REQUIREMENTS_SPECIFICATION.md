# Software Requirements Specification

## Functional requirements

### FR-001 Project management
The system shall create and maintain projects with customer, platform, status,
revision, and responsible-user information.

### FR-002 Weld-point management
The system shall store point ID, part, station, robot, gun, operation, criticality,
material stack, parameters, analysis result, revisions, tests, and approvals.

### FR-003 Engineering analysis
The system shall evaluate current, weld time, force, electrode tip, squeeze, hold,
cooling, coating, adhesive, shunt, material family, and stack-up.

### FR-004 Potential failure probabilities
The system shall provide probability, confidence, severity, dominant factors,
recommended validation tests, and corrective actions.

### FR-005 Model transparency
Every prediction shall expose model name, model version, unit assumptions,
validation status, and applicable range.

### FR-006 Rule hierarchy
Priority shall be:
1. Customer/OEM rule
2. Company standard
3. Validated field model
4. Experimental model
5. Literature
6. General engineering formula

### FR-007 Human approval
Unvalidated or low-confidence results shall not become approved production recipes automatically.

## Non-functional requirements
- NFR-001: Deterministic calculation results for identical inputs.
- NFR-002: Unit validation at API boundary.
- NFR-003: Auditability of changes and approvals.
- NFR-004: On-premise deployment support.
- NFR-005: PostgreSQL production persistence.
- NFR-006: Backend automated test coverage for critical engines.
- NFR-007: No hidden use of image-processing modules.
