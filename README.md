# Spot Welding Parameter Analysis

Professional engineering decision-support software for resistance spot welding
parameter analysis.

> This repository is a separate product. It does **not** contain image processing,
> camera inspection, OpenCV, YOLO, or visual defect classification. Those capabilities
> belong to the separate **Spot Welding Image Processing** product.

## Core capabilities

- Material and sheet-stack analysis
- Current, time, force, squeeze, hold, cooling, and electrode evaluation
- Nugget diameter estimation
- Weld-lobe and DOE optimization
- Model-4 and ensemble model support
- Norm/rule hierarchy and conflict handling
- Project, weld-point, revision, test, and approval workflows
- Parameter-based potential failure probabilities
- Explanation of dominant factors and recommended corrective actions

## Potential failure modes

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

## Architecture

```text
React + TypeScript
        ↓ REST
FastAPI Application API
        ↓
Application Services
        ↓
Engineering Domain Core
        ↓
SQLAlchemy / PostgreSQL
```

## Repository structure

```text
backend/             FastAPI, domain engines, persistence, tests
frontend/            React + TypeScript web application
docs/                Product and software design documentation
.github/              CI, issue templates, pull-request template
docker-compose.yml   Local multi-service environment
```

## Quick start with Docker

```powershell
copy .env.example .env
docker compose up --build
```

- Frontend: `http://localhost:5173`
- API: `http://localhost:8000`
- Swagger: `http://localhost:8000/docs`

## Backend development

```powershell
cd backend
py -m pip install -r requirements.txt
py -m pytest -q
py -m uvicorn app.main:app --reload
```

## Frontend development

```powershell
cd frontend
npm install
npm run dev
```

## Current verification

```text
17 backend tests passed in v1.1 baseline
```

## Documentation

Start with:

1. `docs/00_PRODUCT_SCOPE.md`
2. `docs/01_SOFTWARE_REQUIREMENTS_SPECIFICATION.md`
3. `docs/02_SYSTEM_ARCHITECTURE.md`
4. `docs/03_PROJECT_TREE.md`
5. `docs/06_ENGINEERING_ENGINE.md`
6. `docs/10_FAILURE_PROBABILITY_ENGINE.md`
7. `docs/18_TEST_STRATEGY.md`
8. `docs/23_CLAUDE_REVIEW_GUIDE.md`

## v1.3 verified hardening
- Frontend production build passes.
- Backend tests complete cleanly.
- JWT secret is mandatory.
- Admin bootstrap is optional and environment-driven.
- Docker startup applies Alembic migrations first.
