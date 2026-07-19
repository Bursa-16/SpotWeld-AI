# System Architecture

```mermaid
flowchart LR
    UI[React Frontend] --> API[FastAPI REST API]
    API --> APP[Application Services]
    APP --> ENG[Engineering Domain]
    APP --> RULES[Rule and Compliance Engine]
    APP --> OPT[Optimization Engine]
    APP --> FAIL[Failure Probability Engine]
    APP --> REPO[Repositories]
    REPO --> DB[(PostgreSQL)]
```

## Layer responsibilities

### Frontend
User workflows, validation feedback, result visualization, dashboards.

### API
Authentication, authorization, request/response contracts, error mapping.

### Application
Use-case orchestration. No engineering equations should be embedded here.

### Domain
Pure calculations and engineering decisions. Domain modules should be testable
without HTTP or database access.

### Infrastructure
SQLAlchemy, PostgreSQL, file export, migration, Docker, external adapters.
