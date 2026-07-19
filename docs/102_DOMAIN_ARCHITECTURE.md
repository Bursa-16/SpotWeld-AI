# Domain Architecture

## Domain Modules
- Parameter Engine
- DOE Engine
- Regression Model
- Failure Probability
- Recommendation Engine
- Rule Engine

## Dependency Rule
API -> Application -> Domain -> Repository

Domain must not depend on:
- FastAPI
- SQLAlchemy session
- Environment variables
