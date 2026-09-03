"""
AegisOps — Industrial AI Reliability Platform

Navigation:
    Overview · Incidents · Equipment · Investigate · Ask AegisOps · History
    Memory Explorer · Graph Explorer · Evaluation · System Health · Projection Diagnostics
"""
import streamlit as st

from ui.framework import render_page_header, render_sidebar

st.set_page_config(
    page_title="AegisOps",
    page_icon="⚙️",
    layout="wide",
    initial_sidebar_state="expanded",
)

render_sidebar()

# ─── Home page ─────────────────────────────────────────────────────────────
render_page_header(
    "AegisOps",
    "Industrial AI Operational Memory Platform",
)

st.markdown(
    """
AegisOps is organized into operator workflows and technical administration views.

| Section | Purpose |
|---|---|
| **Operations** | Incidents, Equipment, Investigate, Ask AegisOps, and History |
| **Engineering / Admin** | Memory Explorer, Graph Explorer, Evaluation, System Health, and Projection Diagnostics |

---

**Navigate using the sidebar** to move between operator workflows and technical diagnostics.
    """
)

col1, col2, col3 = st.columns(3)
with col1:
    st.info("🏭 Use **Incidents** to investigate and route operational issues.")
with col2:
    st.info("🧠 Use **Ask AegisOps** for natural-language operational questions.")
with col3:
    st.info("📂 Use **Engineering / Admin** pages for memory, graph, and projection diagnostics.")
