"""Shared Streamlit UI framework for AegisOps pages."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import streamlit as st

from ui.api_client import api_get


_STATUS_ICON = {
    "healthy": "✅",
    "degraded": "⚠️",
    "unhealthy": "❌",
    "unavailable": "⛔",
    "unknown": "⬜",
}


def render_sidebar() -> None:
    """Render the persistent custom sidebar navigation for AegisOps."""

    def page_link(path: str, label: str, icon: str | None = None) -> None:
        kwargs: dict[str, Any] = {"label": label}
        if icon:
            kwargs["icon"] = icon
        st.page_link(path, **kwargs)

    with st.sidebar:
        st.markdown("## AegisOps")
        st.caption("Operational Memory Platform")
        st.divider()
        st.markdown("**Operations**")
        page_link("app.py", "Overview", "📊")
        page_link("pages/06_incident_triage.py", "Incidents", "🏭")
        page_link("pages/02_memory_explorer.py", "Equipment", "🛠️")
        page_link("pages/03_semantic_search.py", "Investigate", "🔎")
        page_link("pages/05_hybrid_graphrag.py", "Ask AegisOps", "🧠")
        page_link("pages/07_working_memory.py", "History", "🕓")

        st.markdown("**Engineering / Admin**")
        page_link("pages/11_memory_explorer.py", "Memory Explorer", "📂")
        page_link("pages/04_graph_explorer.py", "Graph Explorer", "🕸️")
        page_link("pages/08_evaluation.py", "Evaluation", "📈")
        page_link("pages/09_system_health.py", "System Health", "🏥")
        page_link("pages/10_projection_diagnostics.py", "Projection Diagnostics", "🧪")


def render_page_header(title: str, subtitle: str | None = None) -> None:
    st.title(title)
    if subtitle:
        st.caption(subtitle)


def status_badge(status: str) -> str:
    s = (status or "unknown").strip().lower()
    icon = _STATUS_ICON.get(s, _STATUS_ICON["unknown"])
    return f"{icon} {s.replace('_', ' ').title()}"


def render_health_cards(services: dict[str, dict[str, Any]]) -> None:
    if not services:
        render_empty_state("No health information available.")
        return

    cols = st.columns(max(1, min(4, len(services))))
    for i, (name, info) in enumerate(services.items()):
        state = str(info.get("status", "unknown"))
        with cols[i % len(cols)]:
            st.metric(name.upper(), status_badge(state))
            if state not in {"healthy", "degraded"} and info.get("error"):
                st.caption(str(info["error"]))


def render_metric_cards(metrics: Iterable[tuple[str, Any]]) -> None:
    items = list(metrics)
    if not items:
        return
    cols = st.columns(len(items))
    for i, (label, value) in enumerate(items):
        cols[i].metric(label, value)


def render_table(rows: list[dict[str, Any]], *, empty_message: str = "No rows found.") -> None:
    if not rows:
        render_empty_state(empty_message)
        return
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def render_loading(message: str) -> Any:
    return st.spinner(message)


def render_empty_state(message: str) -> None:
    st.info(message)


def render_warning_state(message: str) -> None:
    st.warning(message)


def render_error_state(message: str) -> None:
    st.error(message)


def render_unavailable_state(message: str) -> None:
    st.warning(f"Not available / backend capability not implemented yet: {message}")


def render_dependency_notice(services: dict[str, dict[str, Any]], dependencies: list[str]) -> None:
    degraded: list[str] = []
    for key in dependencies:
        state = str(services.get(key, {}).get("status", "unknown")).lower()
        if state == "degraded":
            degraded.append(key)
    if degraded:
        st.caption(f"Dependency warning: {', '.join(degraded)} service status is degraded.")


def fetch_runtime_health() -> dict[str, dict[str, Any]]:
    """Fetch system health and include API endpoint reachability."""
    api_health = api_get("/health") or {}
    system_health = api_get("/api/v1/system/health") or {}

    services: dict[str, dict[str, Any]] = {}

    if isinstance(api_health, dict) and "error" not in api_health:
        api_status = "healthy" if api_health.get("status") == "ok" else "degraded"
        services["api"] = {"status": api_status}
    else:
        services["api"] = {
            "status": "unavailable",
            "error": api_health.get("error", "API health endpoint unavailable")
            if isinstance(api_health, dict)
            else "API health endpoint unavailable",
        }

    if isinstance(system_health, dict) and "services" in system_health:
        raw_services = system_health.get("services", {})
        if isinstance(raw_services, dict):
            for name, info in raw_services.items():
                if isinstance(info, dict):
                    status = str(info.get("status", "unknown"))
                    services[name] = {
                        "status": status,
                        "error": info.get("error"),
                    }
                else:
                    services[name] = {"status": "unknown"}
    elif isinstance(system_health, dict) and "error" in system_health:
        services.setdefault(
            "system",
            {"status": "unavailable", "error": str(system_health["error"])},
        )

    return services


def capability_available(services: dict[str, dict[str, Any]], required: list[str]) -> tuple[bool, str]:
    missing: list[str] = []
    for key in required:
        state = str(services.get(key, {}).get("status", "unavailable"))
        if state not in {"healthy", "degraded"}:
            missing.append(key)

    if not missing:
        return True, ""

    if len(missing) == 1:
        return False, f"{missing[0]} service is unavailable"

    return False, f"{', '.join(missing)} services are unavailable"
