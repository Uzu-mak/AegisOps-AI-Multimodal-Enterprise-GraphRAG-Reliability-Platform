"""Request identity and canonical row access control.

Local mode is for loopback-only development. Token mode maps opaque tokens to
server-owned tenant/role claims; clients cannot choose their identity.
"""
from __future__ import annotations
import hmac
import json
import os
from contextvars import ContextVar
from dataclasses import dataclass
from sqlalchemy import and_, event, or_
from sqlalchemy.orm import Session, with_loader_criteria
from fastapi.responses import JSONResponse

@dataclass(frozen=True)
class Principal:
    tenant_id: str
    roles: tuple[str, ...]
_identity: ContextVar[Principal | None] = ContextVar("aegisops_identity", default=None)
def current_principal():
    return _identity.get()

def token_principal(token):
    entries = json.loads(os.getenv("AUTH_TOKENS_JSON", "{}"))
    for expected, claims in entries.items():
        if token and hmac.compare_digest(str(token), str(expected)):
            tenant = claims.get("tenant_id")
            roles = claims.get("roles", [])
            if not tenant or not isinstance(roles, list):
                raise ValueError("Invalid server-side token claims")
            return Principal(str(tenant), tuple(str(r) for r in roles))
    return None

READ_ONLY_POSTS = frozenset({
    "/api/v1/search/semantic",
    "/api/v1/search/hybrid",
    "/api/v1/search/graph-related",
    "/api/v1/graphrag/query",
    "/api/v1/investigations",
    "/api/v1/evaluation/runs",
})


async def identity_middleware(request, call_next):
    mode = os.getenv("AUTH_MODE", "local")
    principal = None
    if request.url.path.startswith("/api/") and mode == "token":
        try:
            authorization = request.headers.get("authorization", "")
            principal = token_principal(authorization[7:] if authorization.lower().startswith("bearer ") else "")
        except (ValueError, TypeError):
            return JSONResponse(status_code=503, content={"detail": "Authentication configuration invalid"})
        if principal is None:
            return JSONResponse(status_code=401, content={"detail": "A valid API access token is required"}, headers={"WWW-Authenticate": "Bearer"})
        if request.method not in {"GET", "HEAD", "OPTIONS"} and not set(principal.roles).intersection({"writer", "admin"}):
            # Read-only POST endpoints remain available to viewers. Exact paths
            # only: a substring match would also exempt any future write route
            # nested under one of these (e.g. /evaluation/runs/{id}/promote).
            if request.url.path.rstrip("/") not in READ_ONLY_POSTS:
                return JSONResponse(status_code=403, content={"detail": "Writer role required"})
        if "/system/" in request.url.path and not request.url.path.endswith("/health") and "admin" not in principal.roles:
            return JSONResponse(status_code=403, content={"detail": "Administrator role required for infrastructure metrics"})
    elif mode not in {"local", "token"}:
        return JSONResponse(status_code=503, content={"detail": "Unsupported authentication mode"})
    identity_token = _identity.set(principal)
    try:
        return await call_next(request)
    finally:
        _identity.reset(identity_token)

@event.listens_for(Session, "do_orm_execute")
def _scope_reads(state):
    principal = current_principal()
    if principal is None or not state.is_select:
        return
    from app.db.models.memory import MemoryRecord
    tenant, roles = principal.tenant_id, list(principal.roles)
    state.statement = state.statement.options(with_loader_criteria(
        MemoryRecord,
        lambda cls: and_(cls.tenant_id == tenant, or_(cls.access_roles == [], cls.access_roles.overlap(roles))),
        include_aliases=True,
    ))

@event.listens_for(Session, "before_flush")
def _scope_writes(session, context, instances):
    principal = current_principal()
    if principal is None:
        return
    from app.db.models.memory import MemoryRecord
    from app.services.exceptions import InvalidMemoryDataError
    for record in set(session.new).union(session.dirty):
        if not isinstance(record, MemoryRecord):
            continue
        if record in session.new and record.tenant_id is None:
            record.tenant_id = principal.tenant_id
        if record.tenant_id != principal.tenant_id:
            raise InvalidMemoryDataError("Record tenant must match authenticated tenant")
        if not set(record.access_roles or []).issubset(set(principal.roles)):
            raise InvalidMemoryDataError("Record access roles must be granted to the authenticated principal")
