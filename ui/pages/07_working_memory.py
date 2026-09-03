"""Operational history page."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import streamlit as st

from ui.framework import (
    capability_available,
    fetch_runtime_health,
    render_dependency_notice,
    render_page_header,
    render_sidebar,
    render_unavailable_state,
    status_badge,
)
from ui.operations_catalog import (
    build_area_options,
    build_equipment_options,
    build_facility_options,
    build_record_type_options,
    build_status_options,
    format_memory_type,
    load_memory_records,
)

st.set_page_config(page_title="History — AegisOps", page_icon="🕓", layout="wide", initial_sidebar_state="expanded")
render_sidebar()
render_page_header(
    "History",
    "Operational history for observations, incidents, findings, maintenance actions, resolutions, and recommendations.",
)

services = fetch_runtime_health()
render_dependency_notice(services, ["api", "postgres"])

available, reason = capability_available(services, ["api", "postgres"])
if not available:
    render_unavailable_state(reason)
    st.stop()

records = load_memory_records(limit=500)
facility_options = build_facility_options(records)
area_options = build_area_options(records)
equipment_options = build_equipment_options(records)
record_type_options = build_record_type_options(records)
status_options = build_status_options(records)


def select_option(label: str, options: list[dict[str, object]], key: str) -> dict[str, object] | None:
    if not options:
        st.info(f"No {label.lower()} records are available yet.")
        return None
    selected_label = st.selectbox(label, [option["label"] for option in options], key=key)
    return next(option for option in options if option["label"] == selected_label)


facility = select_option("Facility", facility_options, "history_facility")
area = select_option("Area / Line", area_options, "history_area")
equipment = select_option("Equipment", equipment_options, "history_equipment")
record_type = select_option("Record Type", record_type_options, "history_record_type")
status_option = select_option("Lifecycle Status", status_options, "history_status")

lookback = st.selectbox("Time Filter", ["Last 24 hours", "Last 7 days", "Last 30 days", "All time"])
now = datetime.now(timezone.utc)
cutoff_map = {
    "Last 24 hours": now - timedelta(days=1),
    "Last 7 days": now - timedelta(days=7),
    "Last 30 days": now - timedelta(days=30),
    "All time": None,
}
cutoff = cutoff_map[lookback]

filtered = list(records)
if facility:
    filtered = [record for record in filtered if record.get("facility_id") == facility["value"]]
if area:
    filtered = [record for record in filtered if record.get("component_id") == area["value"]]
if equipment:
    filtered = [record for record in filtered if record.get("asset_id") == equipment["value"]]
if record_type:
    filtered = [record for record in filtered if str(record.get("memory_type", "")).lower() == str(record_type["value"]).lower()]
if status_option:
    filtered = [record for record in filtered if str(record.get("status", "")).lower() == str(status_option["value"]).lower()]
if cutoff:
    recent_filtered = []
    for record in filtered:
        created_at = record.get("created_at")
        try:
            created_dt = datetime.fromisoformat(str(created_at).replace("Z", "+00:00")) if created_at else None
        except ValueError:
            created_dt = None
        if created_dt is None or created_dt >= cutoff:
            recent_filtered.append(record)
    filtered = recent_filtered

st.caption(f"Showing {len(filtered)} history records")

if filtered:
    table_rows = []
    for record in sorted(filtered, key=lambda item: str(item.get("created_at") or ""), reverse=True):
        table_rows.append(
            {
                "Type": format_memory_type(record.get("memory_type")),
                "Title": record.get("title") or "Untitled",
                "Status": status_badge(record.get("status", "unknown")),
                "Facility": facility["label"] if facility else "—",
                "Area / Line": area["label"] if area else "—",
                "Equipment": equipment["label"] if equipment else "—",
                "Confidence": f"{float(record.get('confidence', 0) or 0):.0%}",
                "Importance": f"{float(record.get('importance', 0) or 0):.0%}",
                "Summary": (record.get("content") or "")[:180],
            }
        )
    st.dataframe(table_rows, use_container_width=True, hide_index=True)
else:
    st.info("No history records match the current filters.")

with st.expander("Technical Details"):
    st.json(
        {
            "facility": facility,
            "area": area,
            "equipment": equipment,
            "record_type": record_type,
            "lifecycle_status": status_option,
            "time_filter": lookback,
        }
    )
