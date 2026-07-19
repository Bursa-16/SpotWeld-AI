# Professional Architecture v0.7

React + TypeScript → FastAPI REST API → Application Services → Domain Engineering Core → SQLAlchemy → PostgreSQL

## Added in v0.7
- PostgreSQL runtime service
- SQLAlchemy 2.0 ORM
- Alembic initial migration
- Project CRUD
- Weld-point create/list/detail/update
- Automatic recalculation on weld-point update
- Immutable revision snapshots
- Approval workflow
- React project screen and weld-point wizard

## Data ownership
Engineering calculations remain stateless in the domain layer. Project, weld-point, revision and approval records are persisted by the infrastructure layer.
