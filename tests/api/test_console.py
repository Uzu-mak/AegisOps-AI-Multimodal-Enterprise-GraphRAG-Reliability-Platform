"""The web console is served by the API and references only same-origin assets."""
from __future__ import annotations

import re

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
        assert f"{asset}?v=" in page.text
        r = client.get(f"/console/{asset}")
        assert r.status_code == 200 and len(r.text) > 1000


def test_every_console_module_is_served():
    """console.js loads the rest of the console as ES modules; each import must resolve."""
    client = TestClient(app)
    seen, todo = set(), ["console.js"]
    while todo:
        path = todo.pop()
        if path in seen:
            continue
        seen.add(path)
        r = client.get(f"/console/{path}")
        assert r.status_code == 200, path
        assert "javascript" in r.headers["content-type"], path
        base = path.rsplit("/", 1)[0] + "/" if "/" in path else ""
        for spec in re.findall(r'^import .* from "([^"]+)";', r.text, flags=re.M):
            parts = (base + spec).split("/")
            resolved = []
            for part in parts:
                if part == "..":
                    resolved.pop()
                elif part not in (".", ""):
                    resolved.append(part)
            todo.append("/".join(resolved))
    assert {"lib/api.js", "lib/dom.js", "components/ui.js", "views/investigate.js"} <= seen


def test_console_asset_stamps_are_current():
    """index.html must version every module (scripts/stamp_console.py), or
    browsers can keep running stale console code after a rebuild."""
    import importlib.util
    from pathlib import Path

    script = Path(__file__).resolve().parents[2] / "scripts" / "stamp_console.py"
    spec = importlib.util.spec_from_file_location("stamp_console", script)
    stamp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stamp)
    assert stamp.main(["--check"]) == 0, "run: python scripts/stamp_console.py"
    page = TestClient(app).get("/console/").text
    assert '<script type="importmap">' in page and '"./console.js": "./console.js?v=' in page
