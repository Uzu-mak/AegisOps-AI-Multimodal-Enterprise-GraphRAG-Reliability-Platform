"""System Overview page."""
import streamlit as st
from ui.api_client import api_get, status_badge

st.set_page_config(page_title="Overview — AegisOps", page_icon="📊", layout="wide")
st.title("📊 System Overview")

# Service health
st.subheader("Service Health")
health = api_get("/api/v1/system/health") or {}
services = health.get("services", {})

cols = st.columns(4)
for i, (name, info) in enumerate(services.items()):
    if isinstance(info, dict):
        s = info.get("status", "unknown")
        with cols[i % 4]:
            st.metric(
                label=name.upper(),
                value=status_badge(s),
                delta=info.get("url") or info.get("host") or info.get("uri") or info.get("provider", ""),
            )

st.divider()

# Memory counts
col1, col2 = st.columns([1, 2])
stats = api_get("/api/v1/system/memory-stats") or {}

with col1:
    st.subheader("Memory Counts")
    st.metric("Total Memories", stats.get("total", 0))

    by_status = stats.get("by_status", {})
    if by_status:
        for s, n in by_status.items():
            st.metric(s.capitalize(), n)

with col2:
    st.subheader("By Memory Type")
    import pandas as pd

    by_type = stats.get("by_type", {})
    if by_type:
        df = pd.DataFrame(list(by_type.items()), columns=["Type", "Count"])
        df = df.sort_values("Count", ascending=False)
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("No memory records yet.")

st.divider()

# Recent memories
st.subheader("Recent Memories")
memories = api_get("/api/v1/memories", params={"limit": 5, "offset": 0})
if isinstance(memories, dict) and memories.get("items"):
    for m in memories["items"]:
        with st.expander(f"🔹 {m.get('title', 'Untitled')} — {m.get('memory_type', '')}"):
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Status", m.get("status", ""))
            c2.metric("Confidence", f"{m.get('confidence', 0):.0%}")
            c3.metric("Importance", f"{m.get('importance', 0):.0%}")
            c4.metric("Asset", m.get("asset_id") or "—")
            st.caption(m.get("content", "")[:400])
else:
    st.info("No memories found. Create some via the API or Incident Triage page.")
