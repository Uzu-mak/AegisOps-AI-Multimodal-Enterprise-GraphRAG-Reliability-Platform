"""Incident / Fault Triage page."""
import streamlit as st
from ui.api_client import api_post, api_get

st.set_page_config(page_title="Incident Triage — AegisOps", page_icon="🏭", layout="wide")
st.title("🏭 Incident & Fault Triage")
st.caption(
    "Create and link operational memory records for manufacturing fault analysis. "
    "All entries become canonical PostgreSQL records."
)

tab_create, tab_query = st.tabs(["Create Memory", "Query Incident"])

with tab_create:
    st.subheader("Create Operational Memory Record")
    with st.form("create_memory_form"):
        col1, col2 = st.columns(2)
        memory_type = col1.selectbox(
            "Memory Type",
            ["observation", "incident", "diagnosis", "maintenance_action",
             "resolution", "recommendation", "document_fact"],
        )
        source_type = col2.selectbox(
            "Source Type",
            ["sensor", "operator", "technician", "system", "manual", "document"],
        )

        title = st.text_input("Title *", placeholder="Elevated vibration on pump P-102")
        content = st.text_area("Content *", placeholder="Detailed description of observation...", height=120)

        col3, col4 = st.columns(2)
        asset_id = col3.text_input("Asset ID", placeholder="pump-p102")
        facility_id = col4.text_input("Facility ID", placeholder="facility-west")

        col5, col6 = st.columns(2)
        component_id = col5.text_input("Component ID", placeholder="bearing-main")
        incident_id = col6.text_input("Incident ID", placeholder="inc-2024-0042")

        col7, col8 = st.columns(2)
        confidence = col7.slider("Confidence", 0.0, 1.0, 0.8, 0.05)
        importance = col8.slider("Importance", 0.0, 1.0, 0.7, 0.05)

        submitted = st.form_submit_button("Create Memory Record", type="primary")
        if submitted:
            if not title.strip() or not content.strip():
                st.error("Title and Content are required.")
            else:
                payload = {
                    "memory_type": memory_type,
                    "title": title,
                    "content": content,
                    "source_type": source_type,
                    "asset_id": asset_id or None,
                    "facility_id": facility_id or None,
                    "component_id": component_id or None,
                    "incident_id": incident_id or None,
                    "confidence": confidence,
                    "importance": importance,
                }
                result = api_post("/api/v1/memories", payload)
                if result and "error" not in result and "id" in result:
                    st.success(f"✅ Memory created: `{result['id']}`")
                    with st.expander("Created Record"):
                        st.json(result)
                else:
                    st.error("Failed to create memory.")
                    if result:
                        st.json(result)

with tab_query:
    st.subheader("Query Related Incident Memories")
    q = st.text_input(
        "Describe the fault or incident",
        placeholder="bearing failure vibration fault pump west facility",
    )
    if st.button("Find Related Memories", type="primary") and q:
        with st.spinner("Searching..."):
            result = api_post(
                "/api/v1/search/hybrid",
                {"query": q, "mode": "hybrid", "limit": 10},
            )
        if result and "error" not in result:
            results = result.get("results", [])
            st.write(f"**{len(results)} related memories found:**")
            for r in results:
                with st.expander(f"{r.get('title', '—')} [{r.get('memory_type', '')}]"):
                    st.write(r.get("content_preview", ""))
                    cols = st.columns(3)
                    cols[0].metric("Asset", r.get("asset_id") or "—")
                    cols[1].metric("Status", r.get("status") or "—")
                    cols[2].metric("Confidence", f"{r.get('confidence', 0):.0%}" if r.get("confidence") else "—")
        else:
            st.info("No results found.")
