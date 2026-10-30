"""Request identity and canonical row access control.

Local mode is for loopback-only development. Token mode maps opaque tokens to
server-owned tenant/role claims; clients cannot choose their identity. OIDC
mode accepts signed access tokens from an OpenID Connect provider (see
app/core/oidc.py) and, alongside them, token-mode tokens for scripts.
"""
from __future__ import annotations
import hmac
import json
import os
import re
from contextvars import ContextVar
from dataclasses import dataclass
from sqlalchemy import and_, event, or_
from sqlalchemy.orm import Session, with_loader_criteria
from fastapi.responses import JSONResponse

@dataclass(frozen=True)
class Principal:
    tenant_id: str | None
    roles: tuple[str, ...]
    # Set for people signed in through OIDC; empty for token-mode scripts.
    subject: str | None = None
    issuer: str | None = None
    username: str | None = None
    display_name: str | None = None
    email: str | None = None


def actor_name() -> str | None:
    """The signed-in person's username, used wherever the console used to ask for a name."""
    p = current_principal()
    return getattr(p, "username", None) if p is not None else None
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
# Reviewers may not change data, but they do approve or return question sets.
REVIEW_ACTIONS = re.compile(r"^/api/v1/evaluation/question-sets/[^/]+/(approve|return)$")
# Readable without signing in: what the console needs to start a sign-in.
PUBLIC_PATHS = frozenset({"/api/v1/auth/config"})


def _authenticate(mode: str, token: str):
    """Principal for a bearer token, or None. Raises ValueError on bad server configuration."""
    principal = token_principal(token) if os.getenv("AUTH_TOKENS_JSON") or mode == "token" else None
    if principal is not None or mode != "oidc" or not token:
        return principal
    import jwt

    from app.core import oidc

    settings = oidc.OIDCSettings.from_env()
    try:
        claims = oidc.verify(token, settings)
    except (jwt.InvalidTokenError, jwt.PyJWKClientError):
        return None
    return Principal(**oidc.principal_fields(claims, settings))


async def identity_middleware(request, call_next):
    mode = os.getenv("AUTH_MODE", "local")
    principal = None
    path = request.url.path.rstrip("/")
    if request.url.path.startswith("/api/") and mode in {"token", "oidc"} and path not in PUBLIC_PATHS:
        try:
            authorization = request.headers.get("authorization", "")
            principal = _authenticate(mode, authorization[7:] if authorization.lower().startswith("bearer ") else "")
        except (ValueError, TypeError):
            return JSONResponse(status_code=503, content={"detail": "Authentication configuration invalid"})
        if principal is None:
            return JSONResponse(status_code=401, content={"detail": "Sign in to continue: a valid access token is required"}, headers={"WWW-Authenticate": "Bearer"})
        if principal.subject:
            from starlette.concurrency import run_in_threadpool

            from app.core.users import remember

            await run_in_threadpool(remember, principal)
        if request.method not in {"GET", "HEAD", "OPTIONS"} and not set(principal.roles).intersection({"writer", "admin"}):
            # Read-only POST endpoints remain available to viewers. Exact paths
            # only: a substring match would also exempt any future write route
            # nested under one of these (e.g. /evaluation/runs/{id}/promote).
            allowed = path in READ_ONLY_POSTS or ("reviewer" in principal.roles and REVIEW_ACTIONS.match(path))
            if not allowed:
                return JSONResponse(status_code=403, content={"detail": "Your role can view but not change data (an engineer or administrator role is needed)"})
        if "/system/" in request.url.path and not request.url.path.endswith("/health") and "admin" not in principal.roles:
            return JSONResponse(status_code=403, content={"detail": "Administrator role required for infrastructure metrics"})
    elif mode not in {"local", "token", "oidc"}:
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
    # A single-tenant deployment (no tenant claim) sees records without a tenant.
    criteria = ((lambda cls: and_(cls.tenant_id.is_(None), or_(cls.access_roles == [], cls.access_roles.overlap(roles))))
                if tenant is None else
                (lambda cls: and_(cls.tenant_id == tenant, or_(cls.access_roles == [], cls.access_roles.overlap(roles)))))
    state.statement = state.statement.options(with_loader_criteria(MemoryRecord, criteria, include_aliases=True))

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
