# Phased Implementation Plan

## Purpose

This plan converts the independent architecture review into an implementation sequence. The order is mandatory: runtime reliability first, then quality, architecture, and production hardening.

## Phase 1 — Runtime reliability and CI

### 1.1 Central configuration and JWT lifecycle

Files expected to change:

```text
backend/app/core/config.py
backend/app/core/security.py
backend/app/main.py
backend/app/api/dependencies.py
backend/tests/conftest.py
.env.example
```

Required outcomes:
- no environment validation at module import
- typed settings object
- startup-time production validation
- isolated test secret
- no committed real secret
- clear startup diagnostics

Acceptance:

```text
python -c "from app.main import app; print('IMPORT_OK')"
pytest -q
```

### 1.2 Frontend TypeScript build compatibility

Files expected to change:

```text
frontend/tsconfig.json
frontend/tsconfig.app.json
frontend/tsconfig.node.json
frontend/package.json
```

Required outcomes:
- removed legacy `moduleResolution=node10`
- Vite-compatible TypeScript 5.9 configuration
- clean dependency install and production build

Acceptance:

```text
npm ci
npx tsc -v
npm run build
```

### 1.3 CI expansion

File expected to change:

```text
.github/workflows/ci.yml
```

Required CI jobs:
- backend dependency installation
- backend unit/API tests
- lint
- type checking
- Alembic migration check
- backend import/startup smoke test
- frontend clean installation
- TypeScript build
- Docker Compose configuration validation

Acceptance:
- all GitHub Actions jobs green
- no ignored failing command
- no secret value printed

### 1.4 Docker production alignment

Files expected to change:

```text
backend/Dockerfile
frontend/Dockerfile
docker-compose.yml
```

Required outcomes:
- frontend builds production assets
- frontend is served by a production static server
- backend validates config before service readiness
- migrations execute safely
- health checks are defined

Acceptance:

```text
docker compose config
docker compose build
```

## Phase 2 — Quality and verification

### 2.1 Static analysis

Deliverables:
- backend lint configuration
- backend type-check configuration
- frontend ESLint and TypeScript checks
- CI enforcement

Suggested files:

```text
pyproject.toml
requirements-dev.txt
frontend/package.json
.github/workflows/ci.yml
```

### 2.2 Integration and contract tests

Suggested structure:

```text
backend/tests/integration/
backend/tests/test_auth_flow.py
backend/tests/test_migrations.py
backend/tests/test_openapi_contract.py
```

Required coverage:
- migration from empty DB
- repository CRUD and constraints
- JWT login/token/authorization flows
- unauthorized and forbidden paths
- OpenAPI availability and endpoint contract
- frontend-required endpoint compatibility

### 2.3 Dataset reproducibility

Required outcomes:
- versioned material, electrode, stack and rule datasets
- deterministic seed/import process
- provenance and validation state for every dataset
- no silent empty-dataset operation

## Phase 3 — Architectural separation

### 3.1 Rule provider architecture

Target:

```text
backend/app/domain/rules/
backend/app/domain/rules/providers/
backend/app/application/compliance_service.py
backend/app/repositories/rule_repository.py
```

Required providers:
- Internal
- OEM
- ISO
- AWS
- SEP
- Custom

Acceptance:
- adding a provider does not require changing the evaluator core
- source/version/precedence are traceable

### 3.2 Model registry hardening

Required outcomes:
- model metadata and lifecycle status
- unit and input-range validation
- model version in every result
- explicit extrapolation handling
- verification evidence link

### 3.3 Repository interfaces and dependency inversion

Introduce or standardize:

```text
MaterialRepository
ElectrodeRepository
SheetStackRepository
ProjectRepository
RuleRepository
ModelRepository
AuditRepository
ReportRepository
```

Acceptance:
- domain layer contains no SQLAlchemy/FastAPI/environment imports
- application services depend on interfaces

## Phase 4 — Production hardening

### 4.1 Observability
- structured logs
- correlation IDs
- safe error responses
- audit events
- metrics and health/readiness endpoints

### 4.2 Performance and scalability
- profile optimization and probability endpoints
- cache deterministic repeated calculations
- background jobs only where justified
- DB index review
- load and stress tests

### 4.3 Release governance
- semantic versioning
- changelog enforcement
- model/rule/dataset release manifest
- migration compatibility checks
- reproducible build artifacts
- release approval checklist

## Delivery protocol for every phase

Every delivery must include:

```text
1. Changed files
2. Exact implementation summary
3. Commands executed
4. Test/build outputs
5. Remaining failures or risks
6. Commit message
7. Release-readiness decision
```

No phase is complete based only on documentation or claimed success.
