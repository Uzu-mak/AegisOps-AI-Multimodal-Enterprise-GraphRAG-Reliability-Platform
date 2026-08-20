"""Memory Explorer page."""
import streamlit as st
from ui.api_client import api_get, status_badge

st.set_page_config(page_title="Memory Explorer — AegisOps", page_icon="📂", layout="wide")
st.title("📂 Memory Explorer")
st.caption("Browse and inspect canonical operational memory records from PostgreSQL.")

# Filters
with st.sidebar:
    st.subheader("Filters")
    filt_type = st.selectbox(
        "Memory Type",
        ["", "observation", "incident", "diagnosis", "maintenance_action",
         "resolution", "recommendation", "document_fact", "agent_interaction", "feedback"],
    )
    filt_status = st.selectbox("Status", ["", "active", "archived", "disputed", "superseded"])
    filt_asset = st.text_input("Asset ID")
    filt_facility = st.text_input("Facility ID")
    limit = st.slider("Results per page", 5, 50, 20)

params = {"limit": limit, "offset": 0}
if filt_type:
    params["memory_type"] = filt_type
if filt_status:
    params["status"] = filt_status
if filt_asset:
    params["asset_id"] = filt_asset
if filt_facility:
    params["facility_id"] = filt_facility

data = api_get("/api/v1/memories", params=params) or {}
items = data.get("items", []) if isinstance(data, dict) else []

st.caption(f"Showing {len(items)} records")

if not items:
    st.info("No records match the current filters.")
else:
    import pandas as pd

    table_data = [
        {
            "Title": m.get("title", ""),
            "Type": m.get("memory_type", ""),
            "Status": m.get("status", ""),
            "Asset": m.get("asset_id") or "—",
            "Facility": m.get("facility_id") or "—",
            "Confidence": f"{m.get('confidence', 0):.0%}",
            "Importance": f"{m.get('importance', 0):.0%}",
            "ID": m.get("id", ""),
        }
        for m in items
    ]
    df = pd.DataFrame(table_data)
    st.dataframe(df, use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("Inspect Record")
    selected_id = st.text_input("Paste a Memory ID to inspect")
    if selected_id:
        detail = api_get(f"/api/v1/memories/{selected_id}")
        if detail and "error" not in detail:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Type", detail.get("memory_type", ""))
            c2.metric("Status", detail.get("status", ""))
            c3.metric("Confidence", f"{detail.get('confidence', 0):.0%}")
            c4.metric("Importance", f"{detail.get('importance', 0):.0%}")

            st.markdown(f"**Title:** {detail.get('title', '')}")
            st.markdown(f"**Content:**\n{detail.get('content', '')}")

            with st.expander("Full Record"):
                st.json(detail)
        else:
            st.error(f"Memory not found: {detail}")
