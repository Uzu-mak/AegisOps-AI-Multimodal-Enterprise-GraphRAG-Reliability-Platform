from __future__ import annotations

from contextlib import contextmanager

import ui.framework as framework


@contextmanager
def _noop_sidebar():
    yield


def test_render_sidebar_emits_expected_navigation_links(monkeypatch):
    calls: list[tuple[str, dict[str, object]]] = []

    monkeypatch.setattr(framework.st, "sidebar", _noop_sidebar())
    monkeypatch.setattr(framework.st, "markdown", lambda *args, **kwargs: None)
    monkeypatch.setattr(framework.st, "caption", lambda *args, **kwargs: None)
    monkeypatch.setattr(framework.st, "divider", lambda *args, **kwargs: None)
    monkeypatch.setattr(framework.st, "page_link", lambda path, **kwargs: calls.append((path, kwargs)))

    framework.render_sidebar()

    expected_paths = [
        "app.py",
        "pages/06_incident_triage.py",
        "pages/02_memory_explorer.py",
        "pages/03_semantic_search.py",
        "pages/05_hybrid_graphrag.py",
        "pages/07_working_memory.py",
        "pages/11_memory_explorer.py",
        "pages/04_graph_explorer.py",
        "pages/08_evaluation.py",
        "pages/09_system_health.py",
        "pages/10_projection_diagnostics.py",
    ]

    assert [path for path, _ in calls] == expected_paths
    assert calls[0][1]["label"] == "Overview"
    assert calls[1][1]["label"] == "Incidents"
    assert calls[6][1]["label"] == "Memory Explorer"