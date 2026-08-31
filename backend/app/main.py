
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

import app.models
from app.api.v1.audit import router as audit_router
from app.api.v1.auth import router as auth_router
from app.api.v1.dashboard import router as dashboard_router
from app.api.v1.engineering import router as engineering_router
from app.api.v1.evidence_verification import router as evidence_verification_router
from app.api.v1.failure_probability import router as failure_probability_router
from app.api.v1.health import router as health_router
from app.api.v1.machine_readiness import router as machine_readiness_router
from app.api.v1.optimization import router as optimization_router
from app.api.v1.projects import router as projects_router
from app.api.v1.rule_evaluation import router as rule_evaluation_router
from app.api.v1.rule_registry import router as rule_registry_router
from app.api.v1.tests import router as tests_router
from app.api.v1.weld_analysis import router as weld_analysis_router
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models.entities import User


@asynccontextmanager
async def lifespan(_app: FastAPI):
    with SessionLocal() as db:
        admin_email = os.getenv("ADMIN_EMAIL")
        admin_password = os.getenv("ADMIN_PASSWORD")
        if admin_email and admin_password:
            admin = db.scalar(select(User).where(User.email == admin_email))
            if not admin:
                db.add(User(email=admin_email, full_name="System Administrator", password_hash=hash_password(admin_password), role="System Admin"))
                db.commit()
    yield


app = FastAPI(
    title="Spot Welding Platform API",
    version="1.3.0",
    description="Spot welding parameter analysis and engineering decision-support API",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router, prefix="/api/v1")
app.include_router(failure_probability_router, prefix="/api/v1")
app.include_router(optimization_router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")
app.include_router(dashboard_router, prefix="/api/v1")
app.include_router(engineering_router, prefix="/api/v1")
app.include_router(audit_router, prefix="/api/v1")
app.include_router(rule_evaluation_router, prefix="/api/v1")
app.include_router(machine_readiness_router, prefix="/api/v1")
app.include_router(rule_registry_router, prefix="/api/v1")
app.include_router(evidence_verification_router, prefix="/api/v1")
app.include_router(weld_analysis_router, prefix="/api/v1")
app.include_router(projects_router, prefix="/api/v1")
app.include_router(tests_router, prefix="/api/v1")
