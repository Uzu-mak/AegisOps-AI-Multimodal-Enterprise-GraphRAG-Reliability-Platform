"""OIDC tokens: signature, issuer, audience and expiry are checked; roles map to permissions."""
from __future__ import annotations

import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core import oidc

S = oidc.OIDCSettings(issuer="http://localhost:8080/realms/aegisops", client_id="aegisops-console",
                      jwks_url="unused", roles_claim="realm_access.roles", tenant_claim=None)
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _token(key=KEY, **over):
    now = int(time.time())
    claims = {"iss": S.issuer, "sub": "u-1", "aud": ["aegisops-console", "account"], "azp": "aegisops-console",
              "iat": now, "exp": now + 300, "preferred_username": "bismark", "name": "Bismark Mensah",
              "realm_access": {"roles": ["reviewer", "default-roles-aegisops", "offline_access"]}}
    claims.update(over)
    return jwt.encode({k: v for k, v in claims.items() if v is not None}, key, algorithm="RS256")


def test_valid_token_gives_identity_and_known_roles_only():
    claims = oidc.verify(_token(), S, key=KEY.public_key())
    fields = oidc.principal_fields(claims, S)
    assert fields["username"] == "bismark" and fields["display_name"] == "Bismark Mensah"
    assert fields["roles"] == ("reviewer",) and fields["tenant_id"] is None


@pytest.mark.parametrize("bad", [
    {"key": OTHER},                                   # signed by someone else
    {"iss": "http://evil.example/realms/aegisops"},   # wrong issuer
    {"exp": int(time.time()) - 120},                  # expired (beyond leeway)
    {"aud": ["account"], "azp": "other-client"},      # issued for another client
])
def test_invalid_tokens_are_refused(bad):
    key = bad.pop("key", KEY)
    with pytest.raises(jwt.InvalidTokenError):
        oidc.verify(_token(key=key, **bad), S, key=KEY.public_key())


def test_azp_alone_is_enough_for_providers_that_omit_audience():
    oidc.verify(_token(aud=None), S, key=KEY.public_key())


def test_engineers_and_admins_can_change_data_viewers_and_reviewers_cannot():
    assert "writer" in oidc.effective_roles(["engineer"]) and "writer" in oidc.effective_roles(["admin"])
    assert "writer" not in oidc.effective_roles(["viewer"]) and "writer" not in oidc.effective_roles(["reviewer"])
    assert oidc.effective_roles(["superuser", "viewer"]) == ("viewer",)


def test_public_config_has_no_secrets(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "oidc")
    monkeypatch.setenv("OIDC_ISSUER", S.issuer)
    monkeypatch.setenv("OIDC_CLIENT_ID", S.client_id)
    cfg = oidc.public_config()
    assert cfg["authorization_endpoint"] == S.issuer + "/protocol/openid-connect/auth"
    assert set(cfg) == {"mode", "issuer", "client_id", "authorization_endpoint", "token_endpoint", "end_session_endpoint"}
