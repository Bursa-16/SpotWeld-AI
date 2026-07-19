
from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import decode_token
from app.db.session import get_db
from app.models.entities import User

bearer = HTTPBearer(auto_error=True)

ROLE_PERMISSIONS = {
    "System Admin": {"*"},
    "Process Engineer": {"project:read", "project:write", "weld:read", "weld:write", "approval:read", "test:read"},
    "Quality Engineer": {"project:read", "weld:read", "approval:read", "approval:write", "test:read", "test:write"},
    "Manufacturing Engineer": {"project:read", "weld:read", "weld:write", "test:read"},
    "Maintenance": {"project:read", "weld:read", "test:read"},
    "Operator": {"project:read", "weld:read", "test:read"},
    "Read Only": {"project:read", "weld:read", "approval:read", "test:read"},
    "Customer": {"project:read", "weld:read", "approval:read", "test:read"},
}


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    try:
        email = decode_token(credentials.credentials, "access")
    except ValueError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user = db.scalar(select(User).where(User.email == email))
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Inactive user")
    return user


def require_permission(permission: str):
    def dependency(user: User = Depends(get_current_user)) -> User:
        permissions = ROLE_PERMISSIONS.get(user.role, set())
        if "*" not in permissions and permission not in permissions:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied")
        return user
    return dependency
