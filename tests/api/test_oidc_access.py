"""Signed-in access through the API: identity, role limits, reviewer actions, recorded names."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.core import oidc
from app.db.models.memory import MemoryRecord
from app.db.models.user import AppUser
from app.db.session import SessionLocal
from app.evaluation.datasets import EvalQuestionRecord, EvalQuestionSetRecord
from app.main import app
from app.outbox.models import ProjectionOutboxEvent

PEOPLE = {
    "t-jeremiah": {"sub": "s-1", "preferred_username": "jeremiah", "realm_access": {"roles": ["engineer", "admin"]}},
    "t-bismark": {"sub": "s-2", "preferred_username": "bismark", "realm_access": {"roles": ["reviewer"]}},
    "t-viewer": {"sub": "s-3", "preferred_username": "plant.viewer", "realm_access": {"roles": ["viewer"]}},
}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "oidc")
    monkeypatch.setenv("OIDC_ISSUER", "http://kc/realms/aegisops")
    monkeypatch.setenv("OIDC_CLIENT_ID", "aegisops-console")
    monkeypatch.delenv("AUTH_TOKENS_JSON", raising=False)

    def fake_verify(token, settings=None, *, key=None):
        if token not in PEOPLE:
            import jwt
            raise jwt.InvalidTokenError("unknown")
        return {"iss": "http://kc/realms/aegisops", **PEOPLE[token]}
    monkeypatch.setattr(oidc, "verify", fake_verify)

    def wipe():
        with SessionLocal() as s:
            for model in (EvalQuestionRecord, EvalQuestionSetRecord, ProjectionOutboxEvent, MemoryRecord, AppUser):
                s.execute(delete(model))
            s.commit()
    wipe()
    from app.core import users
    users._last.clear()
    yield TestClient(app)
    wipe()


def _as(token):
    return {"Authorization": f"Bearer {token}"}


def test_config_is_public_and_everything_else_needs_sign_in(client):
    assert client.get("/api/v1/auth/config").json()["mode"] == "oidc"
    assert client.get("/api/v1/memories").status_code == 401
    assert client.get("/api/v1/memories", headers=_as("forged")).status_code == 401


def test_me_shows_who_is_signed_in_and_they_are_remembered(client):
    me = client.get("/api/v1/auth/me", headers=_as("t-jeremiah")).json()
    assert me["username"] == "jeremiah" and {"admin", "engineer", "writer"} <= set(me["roles"])
    users = client.get("/api/v1/auth/users", headers=_as("t-jeremiah")).json()["users"]
    assert [u["username"] for u in users] == ["jeremiah"]
    assert client.get("/api/v1/auth/users", headers=_as("t-viewer")).status_code == 403


def test_roles_limit_changes_and_names_come_from_the_sign_in(client):
    rec = {"memory_type": "incident", "title": "Oil cooler leak", "content": "x", "source_type": "technician", "confidence": 0.8, "importance": 0.5}
    assert client.post("/api/v1/memories", json=rec, headers=_as("t-viewer")).status_code == 403
    assert client.post("/api/v1/memories", json=rec, headers=_as("t-bismark")).status_code == 403
    mid = client.post("/api/v1/memories", json=rec, headers=_as("t-jeremiah")).json()["id"]

    qs = {"name": "S", "author": "someone else", "questions": [{"question": "Where was the oil leak?", "expected_memory_ids": [mid]}]}
    created = client.post("/api/v1/evaluation/question-sets", json=qs, headers=_as("t-jeremiah")).json()
    assert created["created_by"] == "jeremiah"  # the typed name is ignored
    sid = created["id"]
    assert client.post(f"/api/v1/evaluation/question-sets/{sid}/submit", json={}, headers=_as("t-jeremiah")).status_code == 200
    # An engineer who is not a reviewer cannot approve, and a reviewer cannot submit or draft.
    assert client.post(f"/api/v1/evaluation/question-sets/{sid}/approve", json={}, headers=_as("t-viewer")).status_code == 403
    ok = client.post(f"/api/v1/evaluation/question-sets/{sid}/approve", json={"by": "typed name"}, headers=_as("t-bismark"))
    assert ok.status_code == 200, ok.text
    assert ok.json()["reviewed_by"] == "bismark"


def test_admin_cannot_approve_their_own_set(client):
    rec = {"memory_type": "incident", "title": "t", "content": "x", "source_type": "technician", "confidence": 0.8, "importance": 0.5}
    mid = client.post("/api/v1/memories", json=rec, headers=_as("t-jeremiah")).json()["id"]
    sid = client.post("/api/v1/evaluation/question-sets", json={"name": "S2", "questions": [{"question": "Why?", "expected_memory_ids": [mid]}]},
                      headers=_as("t-jeremiah")).json()["id"]
    client.post(f"/api/v1/evaluation/question-sets/{sid}/submit", json={}, headers=_as("t-jeremiah"))
    r = client.post(f"/api/v1/evaluation/question-sets/{sid}/approve", json={}, headers=_as("t-jeremiah"))
    assert r.status_code == 409 and "other than the author" in r.json()["detail"]
