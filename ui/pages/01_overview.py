"""Operational overview page."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import streamlit as st

from ui.api_client import API_URL, api_post
from ui.demo_seed import find_placeholder_records, plan_seed_records
from ui.framework import (
    capability_available,
    fetch_runtime_health,
    render_page_header,
    render_sidebar,
    render_unavailable_state,
    status_badge,
)
from ui.operations_catalog import format_memory_type, load_memory_records

st.set_page_config(page_title="Overview - AegisOps", page_icon="📊", layout="wide", initial_sidebar_state="expanded")
render_sidebar()
render_page_header(
    "Overview",
    "Operational pulse for incidents, observations, and maintenance activity.",
)

services = fetch_runtime_health()

available, reason = capability_available(services, ["api", "postgres"])
if not available:
    render_unavailable_state(reason)
    st.stop()

records = load_memory_records(limit=500)
incident_records = [r for r in records if str(r.get("memory_type", "")).lower() == "incident"]
open_investigations = [
    r
    for r in incident_records
    if str(r.get("status", "")).lower() in {"active", "disputed", "investigating", "open", "escalated", "blocked"}
]

now = datetime.now(timezone.utc)
recent_cutoff = now - timedelta(hours=24)
resolution_cutoff = now - timedelta(days=7)


def parse_created_at(value: object) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


recent_resolutions = [
    r
    for r in records
    if str(r.get("memory_type", "")).lower() == "resolution"
    and (created := parse_created_at(r.get("created_at"))) is not None
    and created >= resolution_cutoff
]


def is_high_critical_issue(record: dict[str, object]) -> bool:
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    severity = str(metadata.get("severity", "")).lower() if isinstance(metadata, dict) else ""
    if severity in {"high", "critical"}:
        return True
    try:
        importance = float(record.get("importance", 0) or 0)
    except (TypeError, ValueError):
        importance = 0.0
    return importance >= 0.8


high_critical_issues = [r for r in open_investigations if is_high_critical_issue(r)]
equipment_requiring_attention = {
    str(r.get("asset_id"))
    for r in open_investigations
    if r.get("asset_id") not in (None, "")
}

summary_cols = st.columns(5)
summary_cols[0].metric("Active Incidents", len([r for r in incident_records if str(r.get("status", "")).lower() == "active"]))
summary_cols[1].metric("High/Critical Issues", len(high_critical_issues))
summary_cols[2].metric("Open Investigations", len(open_investigations))
summary_cols[3].metric("Equipment Requiring Attention", len(equipment_requiring_attention))
summary_cols[4].metric("Recent Resolutions", len(recent_resolutions))

st.subheader("Incident Queue")
if open_investigations:
    queue_rows = []
    for record in sorted(open_investigations, key=lambda item: str(item.get("created_at") or ""), reverse=True)[:25]:
        queue_rows.append(
            {
                "Incident": record.get("title") or "Untitled",
                "Status": status_badge(str(record.get("status", "unknown"))),
                "Facility": record.get("facility_id") or "-",
                "Area / Line": record.get("component_id") or "-",
                "Equipment": record.get("asset_id") or "-",
                "Summary": (record.get("content") or "")[:160],
            }
        )
    st.dataframe(queue_rows, use_container_width=True, hide_index=True)
else:
    st.info("No open investigations are currently active.")

st.subheader("Recent Operational Activity")
if records:
    activity_rows = []
    for record in sorted(records, key=lambda item: str(item.get("created_at") or ""), reverse=True)[:30]:
        activity_rows.append(
            {
                "Type": format_memory_type(record.get("memory_type")),
                "Title": record.get("title") or "Untitled",
                "Status": status_badge(str(record.get("status", "unknown"))),
                "Created": record.get("created_at") or "-",
                "Summary": (record.get("content") or "")[:160],
            }
        )
    st.dataframe(activity_rows, use_container_width=True, hide_index=True)
else:
    st.info("No operational activity found.")

st.subheader("Local Development Data Controls")
is_local_api = API_URL.startswith("http://localhost") or API_URL.startswith("http://127.0.0.1")
if not is_local_api:
    st.warning(
        "Local-only controls are disabled because AEGISOPS_API_URL is not localhost or 127.0.0.1."
    )

placeholder_rows = find_placeholder_records(records)
inspect_col, cleanup_col, seed_col = st.columns(3)

if inspect_col.button("Inspect Placeholder Records"):
    if placeholder_rows:
        st.dataframe(placeholder_rows, use_container_width=True, hide_index=True)
    else:
        st.success("No placeholder records found in canonical memory data.")

apply_cleanup = cleanup_col.checkbox(
    "Allow local placeholder archive cleanup",
    value=False,
    disabled=not is_local_api,
)
if cleanup_col.button("Archive Placeholder Records", disabled=not is_local_api or not apply_cleanup):
    archived = 0
    failed = 0
    for row in placeholder_rows:
        memory_id = row.get("id")
        if not memory_id:
            continue
        result = api_post(f"/api/v1/memories/{memory_id}/archive", {})
        if isinstance(result, dict) and "error" not in result:
            archived += 1
        else:
            failed += 1
    st.success(f"Archived placeholder records: {archived}")
    if failed:
        st.warning(f"Could not archive {failed} record(s).")

apply_seed = seed_col.checkbox(
    "Allow local demo seed",
    value=False,
    disabled=not is_local_api,
)
if seed_col.button("Seed Demo Dataset", disabled=not is_local_api or not apply_seed):
    pending = plan_seed_records(records)
    created = 0
    failed = 0
    for item in pending:
        result = api_post("/api/v1/memories", item)
        if isinstance(result, dict) and "error" not in result:
            created += 1
        else:
            failed += 1
    if pending:
        st.success(f"Demo records created: {created}")
    else:
        st.info("Demo dataset already present. No new records were created.")
    if failed:
        st.warning(f"Could not create {failed} demo record(s).")
