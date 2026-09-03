"""Investigate page."""
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
    build_area_options,
    build_equipment_options,
    build_facility_options,
    build_incident_options,
    format_memory_type,
    load_memory_records,
)

st.set_page_config(page_title="Investigate — AegisOps", page_icon="🔎", layout="wide", initial_sidebar_state="expanded")
render_sidebar()
render_page_header(
    "Investigate",
    "Structured incident investigation with answer, recommended checks, evidence, history, and engineer actions.",
)

services = fetch_runtime_health()
render_dependency_notice(services, ["api", "postgres", "qdrant", "neo4j"])

available, reason = capability_available(services, ["api", "postgres"])
if not available:
    render_unavailable_state(reason)
    st.stop()

records = load_memory_records(limit=500)
facility_options = build_facility_options(records)
area_options = build_area_options(records)
equipment_options = build_equipment_options(records)
incident_options = build_incident_options(records)


def select_option(label: str, options: list[dict[str, object]], key: str) -> dict[str, object] | None:
    if not options:
        st.info(f"No {label.lower()} records are available yet.")
        return None
    selected_label = st.selectbox(label, [option["label"] for option in options], key=key)
    return next(option for option in options if option["label"] == selected_label)


facility = select_option("Facility", facility_options, "investigate_facility")
area = select_option("Area / Line", area_options, "investigate_area")
equipment = select_option("Equipment", equipment_options, "investigate_equipment")
incident = select_option("Incident", incident_options, "investigate_incident")
question = st.text_area(
    "Investigation question",
    placeholder="What is the most likely cause and what should we check next?",
    height=110,
)

context_text = " ".join(
    value
    for value in [
        facility["label"] if facility else None,
        area["label"] if area else None,
        equipment["label"] if equipment else None,
        incident["label"] if incident else None,
        question,
    ]
    if value
)

if st.button("Ask AegisOps", type="primary", disabled=not context_text.strip()):
    with render_loading("Investigating context..."):
        response = api_post(
            "/api/v1/graphrag/query",
            {
                "question": context_text,
                "context_limit": 5,
                "anchor_memory_id": None,
            },
        )
    if response and "error" not in response:
        st.session_state.investigation = response
        st.success("Investigation ready.")
    else:
        render_error_state("Investigation failed.")

investigation = st.session_state.get("investigation", {})

tab_investigation, tab_evidence, tab_history, tab_technical = st.tabs(
    ["Investigation", "Evidence", "History", "Technical Details"]
)

with tab_investigation:
    cols = st.columns(4)
    cols[0].metric("Facility", facility["label"] if facility else "—")
    cols[1].metric("Area / Line", area["label"] if area else "—")
    cols[2].metric("Equipment", equipment["label"] if equipment else "—")
    cols[3].metric("Incident", incident["label"] if incident else "—")

    if investigation:
        st.subheader("Analysis")
        st.markdown(investigation.get("answer", ""))

        evidence = investigation.get("evidence", [])
        confidence_values = [item.get("confidence") for item in evidence if isinstance(item.get("confidence"), (int, float))]
        if confidence_values:
            st.metric("Confidence", f"{sum(confidence_values) / len(confidence_values):.0%}")

        st.subheader("Recommended Checks")
        checks = []
        for item in evidence[:3]:
            title = item.get("title") or format_memory_type(item.get("memory_type"))
            summary = (item.get("content_preview") or item.get("content") or "")[:140]
            checks.append(f"{title}: {summary}" if summary else title)
        if checks:
            for check in checks:
                st.write(f"- {check}")
        else:
            st.info("No recommended checks are available yet.")

        action_cols = st.columns(4)
        if action_cols[0].button("Confirm"):
            st.session_state.setdefault("investigation_actions", []).append("Confirm")
            st.success("Confirmed.")
        if action_cols[1].button("Reject"):
            st.session_state.setdefault("investigation_actions", []).append("Reject")
            st.warning("Rejected.")
        if action_cols[2].button("Add Evidence"):
            st.session_state.setdefault("investigation_actions", []).append("Add Evidence")
            st.info("Evidence captured.")
        if action_cols[3].button("Escalate"):
            st.session_state.setdefault("investigation_actions", []).append("Escalate")
            st.error("Escalated.")
    else:
        st.info("Ask AegisOps to analyze the selected context.")

with tab_evidence:
    evidence = investigation.get("evidence", []) if investigation else []
    if evidence:
        for item in evidence:
            with st.expander(f"{item.get('title', 'Untitled')} [{format_memory_type(item.get('memory_type'))}]"):
                st.metric("Status", status_badge(item.get("status", "unknown")))
                st.markdown(item.get("content_preview") or item.get("content") or "")
    else:
        st.info("No related evidence has been found yet.")

with tab_history:
    if records:
        history_rows = []
        for record in records[:50]:
            history_rows.append(
                {
                    "Type": format_memory_type(record.get("memory_type")),
                    "Title": record.get("title") or "Untitled",
                    "Status": status_badge(record.get("status", "unknown")),
                    "Summary": (record.get("content") or "")[:180],
                }
            )
        st.dataframe(history_rows, use_container_width=True, hide_index=True)
    else:
        st.info("No history records are available yet.")

with tab_technical:
    with st.expander("Technical Details"):
        st.json(
            {
                "facility": facility,
                "area": area,
                "equipment": equipment,
                "incident": incident,
                "question": question,
                "actions": st.session_state.get("investigation_actions", []),
            }
        )
