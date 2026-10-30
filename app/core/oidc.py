"""
Sign-in through any standard OpenID Connect provider (Keycloak, Entra ID, Okta, Clerk).

The console signs people in at the provider (authorization code with PKCE) and
sends the access token with each API call. Here the token's signature is
checked against the provider's published keys (JWKS), along with its issuer,
audience and expiry; the person's roles are read from it. Nothing here is
specific to one provider: switching provider is configuration.

    AUTH_MODE=oidc
    OIDC_ISSUER        issuer as it appears in tokens (the URL the browser uses)
    OIDC_CLIENT_ID     the console's client ID (also the expected audience)
    OIDC_JWKS_URL      where the API fetches signing keys (defaults to issuer + Keycloak's path)
    OIDC_ROLES_CLAIM   dotted path to the roles list (default realm_access.roles)
    OIDC_TENANT_CLAIM  optional claim naming the tenant; unset means single tenant
    OIDC_AUTHORIZATION_ENDPOINT / OIDC_TOKEN_ENDPOINT / OIDC_END_SESSION_ENDPOINT
                       for providers whose paths differ from Keycloak's
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Optional

# Provider roles -> what they allow in AegisOps. "writer" is the internal
# permission to change data, kept from token mode so both modes share checks.
ROLE_GRANTS = {
    "viewer": set(),
    "engineer": {"writer"},
    "reviewer": set(),
    "admin": {"writer"},
    "writer": {"writer"},  # token-mode name, accepted as is
}
KNOWN_ROLES = ("viewer", "engineer", "reviewer", "admin", "writer")


@dataclass(frozen=True)
class OIDCSettings:
    issuer: str
    client_id: str
    jwks_url: str
    roles_claim: str
    tenant_claim: Optional[str]

    @classmethod
    def from_env(cls) -> "OIDCSettings":
        issuer = os.getenv("OIDC_ISSUER", "").rstrip("/")
        if not issuer or not os.getenv("OIDC_CLIENT_ID"):
            raise ValueError("AUTH_MODE=oidc needs OIDC_ISSUER and OIDC_CLIENT_ID")
        return cls(
            issuer=issuer,
            client_id=os.environ["OIDC_CLIENT_ID"],
            jwks_url=os.getenv("OIDC_JWKS_URL") or f"{issuer}/protocol/openid-connect/certs",
            roles_claim=os.getenv("OIDC_ROLES_CLAIM", "realm_access.roles"),
            tenant_claim=os.getenv("OIDC_TENANT_CLAIM") or None,
        )


def effective_roles(raw: list[str]) -> tuple[str, ...]:
    """Known provider roles plus the permissions they grant; unknown roles are ignored."""
    roles = {r for r in raw if r in KNOWN_ROLES}
    for r in list(roles):
        roles |= ROLE_GRANTS.get(r, set())
    return tuple(sorted(roles))


def _claim(claims: dict[str, Any], path: str) -> Any:
    cur: Any = claims
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


@lru_cache(maxsize=4)
def _jwks_client(url: str):
    import jwt

    return jwt.PyJWKClient(url, cache_keys=True, lifespan=600)


def verify(token: str, settings: Optional[OIDCSettings] = None, *, key: Any = None) -> dict[str, Any]:
    """Claims of a valid access token; raises jwt.InvalidTokenError otherwise.

    ``key`` is for tests; normally the key comes from the provider's JWKS.
    """
    import jwt

    s = settings or OIDCSettings.from_env()
    signing_key = key if key is not None else _jwks_client(s.jwks_url).get_signing_key_from_jwt(token).key
    claims = jwt.decode(
        token, signing_key, algorithms=["RS256", "ES256", "PS256"], issuer=s.issuer,
        options={"require": ["exp", "iat", "iss", "sub"], "verify_aud": False}, leeway=30,
    )
    # Providers differ: some put the client in "aud", others only in "azp".
    aud = claims.get("aud")
    audiences = aud if isinstance(aud, list) else [aud] if aud else []
    if s.client_id not in audiences and claims.get("azp") != s.client_id:
        raise jwt.InvalidAudienceError(f"Token was not issued for {s.client_id}")
    return claims


def principal_fields(claims: dict[str, Any], settings: Optional[OIDCSettings] = None) -> dict[str, Any]:
    s = settings or OIDCSettings.from_env()
    raw = _claim(claims, s.roles_claim) or []
    tenant = _claim(claims, s.tenant_claim) if s.tenant_claim else None
    return {
        "tenant_id": str(tenant) if tenant else None,
        "roles": effective_roles([str(r) for r in raw] if isinstance(raw, list) else []),
        "subject": str(claims["sub"]),
        "issuer": str(claims["iss"]),
        "username": claims.get("preferred_username") or claims.get("email") or str(claims["sub"]),
        "display_name": claims.get("name") or claims.get("preferred_username"),
        "email": claims.get("email"),
    }


def public_config() -> dict[str, Any]:
    """What the console needs to start a sign-in. Contains no secrets."""
    mode = os.getenv("AUTH_MODE", "local")
    if mode != "oidc":
        return {"mode": mode}
    s = OIDCSettings.from_env()
    # Keycloak's paths by default; other providers set them (see their discovery document).
    ep = lambda name, path: os.getenv(name) or f"{s.issuer}/protocol/openid-connect/{path}"  # noqa: E731
    return {"mode": "oidc", "issuer": s.issuer, "client_id": s.client_id,
            "authorization_endpoint": ep("OIDC_AUTHORIZATION_ENDPOINT", "auth"),
            "token_endpoint": ep("OIDC_TOKEN_ENDPOINT", "token"),
            "end_session_endpoint": ep("OIDC_END_SESSION_ENDPOINT", "logout")}
