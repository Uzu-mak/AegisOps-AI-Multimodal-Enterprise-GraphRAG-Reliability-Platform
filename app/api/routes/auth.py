"""Sign-in configuration and the signed-in person."""
from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException

from app.core import oidc
from app.core.security import current_principal
from app.core.users import list_users
from app.db.session import SessionLocal

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.get("/config")
def auth_config() -> dict:
    """Public: how the console should sign people in. No secrets."""
    try:
        return oidc.public_config()
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@router.get("/me")
def me() -> dict:
    """Who this request is from. In local mode nobody is signed in and everything is allowed."""
    p = current_principal()
    if p is None:
        return {"mode": os.getenv("AUTH_MODE", "local"), "signed_in": False, "roles": ["admin", "writer", "reviewer"]}
    return {"mode": os.getenv("AUTH_MODE", "local"), "signed_in": bool(p.subject), "username": p.username,
            "display_name": p.display_name, "email": p.email, "roles": list(p.roles), "tenant_id": p.tenant_id}


@router.get("/users")
def users() -> dict:
    """People who have signed in (administrators only)."""
    p = current_principal()
    if p is not None and "admin" not in p.roles:
        raise HTTPException(status_code=403, detail="Administrator role required")
    with SessionLocal() as session:
        return {"users": list_users(session)}
