"""Incidents operations page."""
from __future__ import annotations

import streamlit as st

from ui.api_client import api_post
from ui.framework import (
    capability_available,
    fetch_runtime_health,
    render_dependency_notice,
    render_error_state,
    render_loading,
    render_page_header,
    render_sidebar,
    render_unavailable_state,
    status_badge,
)
from ui.operations_catalog import (
    build_cascading_context_options,
    filter_records_by_context,
    format_memory_type,
    format_status,
    load_memory_records,
)

st.set_page_config(page_title="Incidents — AegisOps", page_icon="🏭", layout="wide", initial_sidebar_state="expanded")
render_sidebar()
render_page_header(
    "Incidents",
    "Context-driven incident investigation for facility, line, equipment, evidence, and engineer action.",
)

services = fetch_runtime_health()
render_dependency_notice(services, ["api", "postgres", "qdrant", "neo4j"])

available, reason = capability_available(services, ["api", "postgres"])
if not available:
    render_unavailable_state(reason)
    st.stop()

records = load_memory_records(limit=500)

fault_options = [
    "Vibration",
    "Temperature",
    "Pressure",
    "Leak",
    "Electrical",
    "Lubrication",
    "Sensor Fault",
    "Noise",
    "Manual Report",
    "Other",
]
status_options = ["Open", "Investigating", "Blocked", "Escalated", "Resolved"]


def select_option(
    label: str,
    options: list[dict[str, object]],
    key: str,
    empty_message: str,
) -> dict[str, object] | None:
    if not options:
        st.caption(empty_message)
        return None

    labels = [option["label"] for option in options]
    selected_label = st.selectbox(label, labels, key=key, placeholder=f"Select {label}")
    return next(option for option in options if option["label"] == selected_label)


def as_rows(items: list[dict[str, object]], kind: str) -> list[dict[str, object]]:
    rows = []
    for item in items:
        rows.append(
            {
                "Type": format_memory_type(item.get("memory_type")),
                "Title": item.get("title") or "Untitled",
                "Status": status_badge(str(item.get("status", "unknown"))),
                "Confidence": f"{float(item.get('confidence', 0) or 0):.0%}",
                "Summary": (item.get("content") or "")[:180],
                "Kind": kind,
            }
        )
    return rows


st.session_state.setdefault("incident_actions", [])

investigation_tab, evidence_tab, history_tab, technical_tab = st.tabs(
    ["Investigation", "Evidence", "History", "Technical Details"]
)

with investigation_tab:
    st.subheader("Incident Context")
    context_options = build_cascading_context_options(records)
    facility = select_option(
        "Facility",
        context_options["facility"],
        "incident_facility",
        "No facility context available",
    )

    selected_facility_id = facility["value"] if facility else None
    context_options = build_cascading_context_options(records, facility_id=selected_facility_id)
    area = select_option(
        "Area / Line",
        context_options["area"],
        "incident_area",
        "No area or line context available for the selected facility",
    )

    selected_area_id = area["value"] if area else None
    context_options = build_cascading_context_options(
        records,
        facility_id=selected_facility_id,
        area_id=selected_area_id,
    )
    equipment = select_option(
        "Equipment",
        context_options["equipment"],
        "incident_equipment",
        "No equipment is available for the selected context",
    )

    selected_equipment_id = equipment["value"] if equipment else None
    context_options = build_cascading_context_options(
        records,
        facility_id=selected_facility_id,
        area_id=selected_area_id,
        equipment_id=selected_equipment_id,
    )
    incident = select_option(
        "Incident",
        context_options["incident"],
        "incident_record",
        "No active incident is selected",
    )

    fault_alarm = st.selectbox("Fault / Alarm", fault_options)
    incident_status = st.selectbox("Status", status_options)
    certainty = st.selectbox("Certainty", ["Confirmed", "Likely", "Possible", "Uncertain"], index=1)
    impact = st.selectbox("Impact", ["Low", "Moderate", "High", "Critical"], index=1)
    engineer_note = st.text_area(
        "Engineer observation",
        placeholder="Describe the symptom, what changed, and any likely cause.",
        height=120,
    )

    selected_records = filter_records_by_context(
        records,
        facility_id=selected_facility_id,
        area_id=selected_area_id,
        equipment_id=selected_equipment_id,
        incident_id=incident["value"] if incident else None,
    )

    started_at = None
    if selected_records:
        started_at = sorted(
            [r.get("created_at") for r in selected_records if r.get("created_at")],
            reverse=False,
        )
        started_at = started_at[0] if started_at else None

    st.markdown("**INCIDENT CONTEXT**")
    context_line_1 = " · ".join(
        part
        for part in [
            equipment["label"] if equipment else None,
            area["label"] if area else None,
        ]
        if part
    ) or "No equipment context selected"
    context_line_2 = incident["label"] if incident else "No active incident is selected"
    st.caption(context_line_1)
    st.caption(context_line_2)
    st.caption(f"Status: {status_badge(incident_status)}")
    st.caption(f"Facility: {facility['label'] if facility else 'No facility context available'}")
    st.caption(f"Fault / Alarm: {fault_alarm}")
    if started_at:
        st.caption(f"Started: {started_at}")

    query_context = " ".join(
        part
        for part in [
            facility["label"] if facility else None,
            area["label"] if area else None,
            equipment["label"] if equipment else None,
            incident["label"] if incident else None,
            fault_alarm,
            f"certainty {certainty}",
            f"impact {impact}",
            engineer_note,
        ]
        if part
    )

    ask = st.button("Ask AegisOps", type="primary", disabled=not query_context.strip())
    if ask:
        with render_loading("Analyzing incident context..."):
            result = api_post(
                "/api/v1/graphrag/query",
                {
                    "question": query_context,
                    "context_limit": 5,
                    "anchor_memory_id": None,
                },
            )

        if result and "error" not in result:
            st.session_state.incident_analysis = result
            st.success("Analysis ready.")
        else:
            render_error_state("Incident analysis failed.")

    analysis = st.session_state.get("incident_analysis", {})
    if analysis:
        st.divider()
        st.subheader("Analysis")
        st.markdown(analysis.get("answer", ""))

        evidence_items = analysis.get("evidence", [])
        confidence_values = [item.get("confidence") for item in evidence_items if isinstance(item.get("confidence"), (int, float))]
        if confidence_values:
            st.metric("Confidence", f"{sum(confidence_values) / len(confidence_values):.0%}")

        st.subheader("Recommended Checks")
        recommended_checks = []
        for item in evidence_items[:3]:
            title = item.get("title") or format_memory_type(item.get("memory_type"))
            summary = (item.get("content_preview") or item.get("content") or "")[:140]
            recommended_checks.append(f"{title}: {summary}" if summary else title)
        if recommended_checks:
            for check in recommended_checks:
                st.write(f"- {check}")
        else:
            st.info("No recommended checks available yet.")

        action_col1, action_col2, action_col3, action_col4 = st.columns(4)
        if action_col1.button("Confirm"):
            st.session_state.incident_actions.append({"action": "Confirm", "status": incident_status, "certainty": certainty, "impact": impact})
            st.success("Incident confirmed.")
        if action_col2.button("Reject"):
            st.session_state.incident_actions.append({"action": "Reject", "status": incident_status, "certainty": certainty, "impact": impact})
            st.warning("Incident rejected.")
        if action_col3.button("Add Observation"):
            st.session_state.incident_actions.append({"action": "Add Observation", "status": incident_status, "certainty": certainty, "impact": impact})
            st.info("Observation added to the incident log.")
        if action_col4.button("Escalate"):
            st.session_state.incident_actions.append({"action": "Escalate", "status": incident_status, "certainty": certainty, "impact": impact})
            st.error("Incident escalated.")

with evidence_tab:
    st.subheader("Evidence")
    relevant = filter_records_by_context(
        records,
        facility_id=selected_facility_id,
        area_id=selected_area_id,
        equipment_id=selected_equipment_id,
        incident_id=incident["value"] if incident else None,
    )
    evidence_rows = [record for record in relevant if str(record.get("memory_type", "")).lower() in {"observation", "incident", "diagnosis", "recommendation", "resolution"}]
    if evidence_rows:
        st.dataframe(as_rows(evidence_rows[:50], "evidence"), use_container_width=True, hide_index=True)
    else:
        st.info("No related evidence has been found yet.")

with history_tab:
    st.subheader("Maintenance History")
    relevant = filter_records_by_context(
        records,
        facility_id=selected_facility_id,
        area_id=selected_area_id,
        equipment_id=selected_equipment_id,
    )
    history_rows = [record for record in relevant if str(record.get("memory_type", "")).lower() in {"maintenance_action", "resolution", "recommendation", "incident", "observation"}]
    if history_rows:
        st.dataframe(as_rows(history_rows[:50], "history"), use_container_width=True, hide_index=True)
    else:
        st.info("No maintenance history is available for this incident context.")

with technical_tab:
    st.subheader("Technical Details")
    with st.expander("Incident context details"):
        st.json(
            {
                "facility": facility,
                "area": area,
                "equipment": equipment,
                "incident": incident,
                "fault_alarm": fault_alarm,
                "incident_status": incident_status,
                "certainty": certainty,
                "impact": impact,
            }
        )
    with st.expander("Raw action log"):
        st.json(st.session_state.get("incident_actions", []))
