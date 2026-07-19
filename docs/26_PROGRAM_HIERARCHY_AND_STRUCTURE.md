# Program Hierarchy and Structure

## 1. Product boundary

**Spot Welding Parameter Assistance** is an independent engineering decision-support product for resistance spot welding parameter analysis.

Included:
- material and coating inputs
- sheet-stack definition
- electrode and gun capability inputs
- current, time, force, squeeze, hold and cooling analysis
- nugget diameter estimation
- weld-lobe and DOE/regression evaluation
- potential failure probabilities
- parameter-based recommendations
- rule, norm and OEM compliance evaluation
- project, revision, test and approval workflows
- technical reports and audit traceability

Excluded:
- camera inspection
- image processing
- OpenCV
- YOLO, CNN, ResNet
- weld-image classification
- visual defect recognition

Those capabilities belong to the separate **Spot Welding Image Processing** product.

## 2. Top-level hierarchy

```text
Spot-Welding-Parametre-Assistance/
├── .github/                 CI, templates, automation
├── backend/                 FastAPI application and engineering core
├── frontend/                React + TypeScript web interface
├── docs/                    Product, software and validation documentation
├── docker-compose.yml       Local/controlled multi-service environment
├── .env.example             Non-secret environment template
├── README.md                Entry point and verified baseline
├── ROADMAP.md               Product-level roadmap
├── CHANGELOG.md             Version history
└── SECURITY.md              Security policy
```

## 3. Logical architecture

```text
User Interface
    ↓
REST API / Authentication / Validation
    ↓
Application Services / Use Cases
    ↓
Engineering Domain Core
    ├── Parameter Analysis
    ├── Nugget Estimation
    ├── DOE / Regression
    ├── Failure Probability
    ├── Recommendation
    ├── Rule / Norm Compliance
    └── Explainability
    ↓
Repositories / Persistence / Model Registry
    ↓
PostgreSQL / Versioned datasets / Model artifacts
```

## 4. Backend hierarchy

Target structure:

```text
backend/app/
├── api/
│   ├── dependencies.py
│   └── v1/
│       ├── auth.py
│       ├── projects.py
│       ├── engineering.py
│       ├── optimization.py
│       ├── failure_probability.py
│       ├── weld_analysis.py
│       ├── audit.py
│       └── dashboard.py
├── application/
│   ├── analysis_service.py
│   ├── optimization_service.py
│   ├── compliance_service.py
│   ├── recommendation_service.py
│   ├── reporting_service.py
│   └── project_service.py
├── domain/
│   ├── analysis/
│   ├── optimization/
│   ├── probability/
│   ├── recommendations/
│   ├── rules/
│   │   └── providers/
│   ├── materials/
│   ├── electrodes/
│   ├── stackups/
│   └── models/
├── repositories/
│   ├── interfaces/
│   └── sqlalchemy/
├── models/
├── schemas/
├── core/
│   ├── config.py
│   ├── security.py
│   ├── logging.py
│   └── exceptions.py
├── data/
│   ├── models/
│   ├── materials/
│   ├── electrodes/
│   └── rules/
└── main.py
```

### Boundary rules

- `domain/` must not import FastAPI, SQLAlchemy sessions or environment variables.
- `application/` orchestrates use cases and depends on repository interfaces.
- `api/` performs request validation, authorization and response mapping only.
- `core/config.py` owns typed configuration and startup validation.
- `core/security.py` performs token/password operations but must not validate environment variables during module import.
- `repositories/` owns persistence implementation.
- Engineering models must declare version, units, valid range, source, validation status and confidence.

## 5. Frontend hierarchy

Target structure:

```text
frontend/src/
├── app/                     routing, providers, global configuration
├── api/                     typed API client and endpoint modules
├── components/              reusable UI components
├── features/
│   ├── projects/
│   ├── weld-analysis/
│   ├── optimization/
│   ├── compliance/
│   ├── probability/
│   ├── recommendations/
│   └── reports/
├── pages/                   route-level screens
├── types/                   shared TypeScript types
├── validation/              input and response validation
├── state/                   controlled application state
├── utils/
└── styles/
```

### UI flow

```text
Home
  → Project
    → Weld Point / Sheet Stack
      → Parameter Entry
        → Analysis
          → Risk and Failure Probability
            → Recommendation
              → Compliance
                → Report / Revision / Approval
```

## 6. Domain hierarchy

### 6.1 Engineering Calculation Context
- parameter normalization
- unit validation
- nugget estimation
- weld-lobe calculation
- derived engineering indicators

### 6.2 Optimization Context
- DOE model execution
- regression/polynomial models
- constrained search
- objective and penalty functions
- recommended parameter window

### 6.3 Risk and Failure Probability Context
- expulsion
- insufficient fusion
- small nugget
- excessive indentation
- electrode sticking/wear
- coating damage
- LME/surface cracking risk
- shunt and cooling instability

### 6.4 Rule and Norm Compliance Context
- internal engineering rules
- OEM rules
- ISO/AWS/SEP rule providers
- conflict resolution and precedence
- traceable rule source/version

### 6.5 Project and Workflow Context
- project
- weld point
- revision
- test record
- approval
- audit event
- report

## 7. Repository interfaces

Required interfaces:

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

Application services depend on these interfaces; SQLAlchemy implementations remain replaceable.

## 8. Model registry

Every engineering model must register:

- unique model ID
- display name
- semantic version
- owner/source
- input names and units
- output names and units
- supported material/stack domain
- training/calibration dataset reference
- valid input range
- extrapolation behavior
- verification status
- confidence and uncertainty information
- activation/deprecation status

Model status values:

```text
DRAFT
REVIEW
VERIFIED
RELEASED
DEPRECATED
```

## 9. Rule provider hierarchy

```text
RuleRegistry
├── InternalRuleProvider
├── OEMRuleProvider
├── ISORuleProvider
├── AWSRuleProvider
├── SEPRuleProvider
└── CustomRuleProvider
```

A rule provider returns normalized rules and source metadata. The evaluation engine must not contain hardcoded source-specific branching.

## 10. Configuration hierarchy

Priority order:

```text
Explicit runtime environment
    → deployment-specific .env
        → safe development defaults
            → application constants
```

Rules:
- production secrets are mandatory
- test secrets are isolated and non-production
- no real secret is committed
- configuration is loaded once through a typed settings object
- startup validation produces clear errors

## 11. Test hierarchy

```text
Unit tests
  → domain calculations and invariants
Integration tests
  → repositories, DB and migrations
API tests
  → auth, validation, status codes, schemas
Contract tests
  → OpenAPI and frontend expectations
Smoke tests
  → import, startup, health and Docker
End-to-end tests
  → critical user workflows
```

## 12. Traceability hierarchy

```text
Requirement
  → Architecture component
    → Source file/module
      → Test case
        → Build result
          → Release version
```

Every released engineering result should record:
- calculation ID
- model/rule versions
- input parameters and units
- warnings
- confidence or applicability limits
- timestamp
- user/project/revision
- formula/model trace where applicable
