"""The web console is served by the API and references only same-origin assets."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_root_redirects_to_console():
    resp = TestClient(app).get("/", follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert resp.headers["location"] == "/console/"


def test_console_shell_and_assets_are_served():
    client = TestClient(app)
    page = client.get("/console/")
    assert page.status_code == 200
    assert 'lang="en"' in page.text
    assert 'class="skip-link"' in page.text
    for asset in ("console.css", "console.js"):
        assert asset in page.text
        r = client.get(f"/console/{asset}")
        assert r.status_code == 200 and len(r.text) > 1000
