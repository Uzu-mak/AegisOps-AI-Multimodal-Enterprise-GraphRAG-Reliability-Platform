"""Equipment operations page."""
from __future__ import annotations

from collections import Counter

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
    format_memory_type,
    humanize_identifier,
    load_memory_records,
)

st.set_page_config(page_title="Equipment — AegisOps", page_icon="🛠️", layout="wide", initial_sidebar_state="expanded")
render_sidebar()
render_page_header(
    "Equipment",
    "Searchable equipment context with current state, related incidents, recent observations, maintenance history, and recurring issues.",
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


def select_option(label: str, options: list[dict[str, object]], key: str) -> dict[str, object] | None:
    if not options:
        st.info(f"No {label.lower()} records are available yet.")
        return None
    selected_label = st.selectbox(label, [option["label"] for option in options], key=key)
    return next(option for option in options if option["label"] == selected_label)


def filter_equipment_records(*, facility_id=None, area_id=None, equipment_id=None) -> list[dict[str, object]]:
    filtered = list(records)
    if facility_id:
        filtered = [record for record in filtered if record.get("facility_id") == facility_id]
    if area_id:
        filtered = [record for record in filtered if record.get("component_id") == area_id]
    if equipment_id:
        filtered = [record for record in filtered if record.get("asset_id") == equipment_id]
    return filtered


facility = select_option("Facility", facility_options, "equipment_facility")
area = select_option("Area / Line", area_options, "equipment_area")
equipment = select_option("Equipment", equipment_options, "equipment_asset")

filtered_records = filter_equipment_records(
    facility_id=facility["value"] if facility else None,
    area_id=area["value"] if area else None,
    equipment_id=equipment["value"] if equipment else None,
)

tab_overview, tab_incidents, tab_observations, tab_maintenance, tab_technical = st.tabs(
    ["Overview", "Incidents", "Observations", "Maintenance", "Technical Details"]
)

with tab_overview:
    context_columns = st.columns(3)
    context_columns[0].metric("Facility", facility["label"] if facility else "—")
    context_columns[1].metric("Area / Line", area["label"] if area else "—")
    context_columns[2].metric("Equipment", equipment["label"] if equipment else "—")

    if filtered_records:
        latest_record = sorted(filtered_records, key=lambda record: str(record.get("created_at") or ""), reverse=True)[0]
        st.metric("Current State", status_badge(latest_record.get("status", "unknown")))
        st.markdown(f"**Latest record:** {latest_record.get('title') or humanize_identifier(equipment['label'] if equipment else 'Equipment')}")
        st.caption((latest_record.get("content") or "")[:320])
    else:
        st.info("No current equipment state is available yet.")

    recurring_titles = Counter(
        (record.get("title") or "").strip().lower()
        for record in filtered_records
        if record.get("title")
    )
    recurring_issues = [title for title, count in recurring_titles.items() if count > 1]
    if recurring_issues:
        st.subheader("Known Recurring Issues")
        for issue in recurring_issues[:5]:
            st.write(f"- {humanize_identifier(issue)}")

with tab_incidents:
    incidents = [record for record in filtered_records if str(record.get("memory_type", "")).lower() == "incident" or record.get("incident_id")]
    if incidents:
        st.dataframe(
            [
                {
                    "Incident": record.get("title") or "Incident",
                    "Status": status_badge(record.get("status", "unknown")),
                    "Confidence": f"{float(record.get('confidence', 0) or 0):.0%}",
                    "Summary": (record.get("content") or "")[:180],
                }
                for record in incidents[:50]
            ],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No related incidents have been found for this equipment.")

with tab_observations:
    observations = [record for record in filtered_records if str(record.get("memory_type", "")).lower() == "observation"]
    if observations:
        st.dataframe(
            [
                {
                    "Observation": record.get("title") or "Observation",
                    "Status": status_badge(record.get("status", "unknown")),
                    "Confidence": f"{float(record.get('confidence', 0) or 0):.0%}",
                    "Summary": (record.get("content") or "")[:180],
                }
                for record in observations[:50]
            ],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No recent observations have been found for this equipment.")

with tab_maintenance:
    maintenance = [
        record
        for record in filtered_records
        if str(record.get("memory_type", "")).lower() in {"maintenance_action", "resolution", "recommendation"}
    ]
    if maintenance:
        st.dataframe(
            [
                {
                    "Record": record.get("title") or format_memory_type(record.get("memory_type")),
                    "Type": format_memory_type(record.get("memory_type")),
                    "Status": status_badge(record.get("status", "unknown")),
                    "Summary": (record.get("content") or "")[:220],
                }
                for record in maintenance[:50]
            ],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No maintenance history is available for this equipment.")

with tab_technical:
    with st.expander("Equipment context details"):
        st.json(
            {
                "facility": facility,
                "area": area,
                "equipment": equipment,
                "record_count": len(filtered_records),
            }
        )
    with st.expander("Raw matching records"):
        st.json(filtered_records[:10])
