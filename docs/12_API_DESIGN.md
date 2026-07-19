# API Design

## Conventions
- Base path: `/api/v1`
- JSON request/response unless exporting files
- Pydantic validation
- Bearer authentication
- Consistent HTTP error semantics

## Important endpoints
- `/auth/*`
- `/projects`
- `/projects/{id}/weld-points`
- `/weld-analysis`
- `/engineering/weld-lobe`
- `/optimization/*`
- `/failure-probability/analyze`
- `/dashboard`
- `/audit`

Swagger is exposed at `/docs` in development.
