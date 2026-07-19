# 100 – Software Design Specification (SDS) Master Index

**Project:** Spot Welding Parametre Analysis

**Document ID:** SDS-100

**Version:** 1.0

**Status:** Draft

**Repository:** Spot-Welding-Parametre-Assistance

**Product Type:** Engineering Analysis Software

## 1. Purpose

This document is the master index of the Software Design Specification (SDS) for the Spot Welding Parametre Analysis software.

It defines the engineering documentation hierarchy, traceability structure, subsystem ownership and relationships.

## 2. Product Scope

The software analyses resistance spot welding parameters and predicts:

- Weld quality
- Nugget diameter
- Failure probability
- Parameter compliance
- Process risks
- Engineering recommendations

### Out of Scope

- OpenCV
- Image Processing
- YOLO
- CNN
- ResNet
- Camera-based inspection

## 3. Repository Structure

```text
backend/
frontend/
docs/
.github/
tests/
docker/
```

## 4. Documentation Hierarchy

- 100 SDS Master Index
- 101 System Context
- 102 Domain Architecture
- 103 Backend Architecture
- 104 Frontend Architecture
- 105 Database Design
- 106 API Design
- 107 Security
- 108 Configuration
- 109 Rule Engine
- 110 Recommendation Engine

## 5. Software Architecture

Layers:

- Presentation
- Application
- Domain
- Infrastructure

Rules:

- Domain must not depend on FastAPI.
- Domain must not depend on SQLAlchemy.
- Domain must not depend on environment variables.

## 6. Major Subsystems

- Backend
- Frontend
- Domain
- Infrastructure

## 7. Domain Modules

- Parameter Analysis Engine
- Recommendation Engine
- Rule Engine
- Model Registry
- DOE Engine
- Regression Engine
- Failure Probability
- Reporting Engine

## 8. Standards

- ISO
- AWS
- SEP
- OEM Rules

## 9. Development Phases

### Phase 1
- JWT
- Configuration
- TypeScript
- CI/CD
- Docker

### Phase 2
- Rule Providers
- Model Registry
- Integration Tests

### Phase 3
- DDD
- Performance
- Plugin Architecture

### Phase 4
- Production Hardening
- Security
- Observability

## 10. References

- Clean Architecture
- Domain Driven Design
- SOLID
- FastAPI
- React
- TypeScript

---
End of Document
