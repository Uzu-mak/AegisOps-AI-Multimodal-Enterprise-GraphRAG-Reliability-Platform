"""
AegisOps — Industrial AI Reliability Platform

Navigation:
  Overview · Memory Explorer · Semantic Search · Graph Explorer
  Hybrid/GraphRAG · Incident Triage · Working Memory · Evaluation · System Health
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
AegisOps integrates three complementary memory layers to power evidence-grounded
operational intelligence for manufacturing reliability and infrastructure management.

| Layer | Technology | Purpose |
|---|---|---|
| **Canonical Memory** | PostgreSQL | Single source of truth for all operational memories |
| **Semantic Memory** | Qdrant | Vector similarity search over memory content |
| **Graph Memory** | Neo4j | Relationship traversal (assets, incidents, components) |
| **Hybrid Retrieval** | Combined | Semantic + graph + canonical hydration |
| **GraphRAG** | LLM + Evidence | Grounded answers with explicit citations |

---

**Navigate using the sidebar** to explore memory records, run searches, triage incidents,
and inspect the AI reasoning pipeline.
    """
)

col1, col2, col3 = st.columns(3)
with col1:
    st.info("📂 Use **Memory Explorer** to inspect and filter canonical records.")
with col2:
    st.info("🔍 Use **Semantic Search** or **Hybrid/GraphRAG** for AI-powered queries.")
with col3:
    st.info("🏥 Use **Incident Triage** to create and link operational memories.")
