"""
AegisOps — Industrial AI Reliability Platform

Navigation:
  Overview · Memory Explorer · Semantic Search · Graph Explorer
  Hybrid/GraphRAG · Incident Triage · Working Memory · Evaluation · System Health
"""
import streamlit as st

st.set_page_config(
    page_title="AegisOps",
    page_icon="⚙️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── Sidebar branding ──────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## ⚙️ AegisOps")
    st.caption("Industrial AI Reliability Platform")
    st.divider()
    st.markdown(
        """
**Navigation**

Use the pages in the sidebar to explore:

- **Overview** — System status & recent memories
- **Memory Explorer** — Browse & inspect canonical records
- **Semantic Search** — Vector similarity search
- **Graph Explorer** — Relationship traversal
- **Hybrid / GraphRAG** — Evidence-grounded answers
- **Incident Triage** — Fault workflow
- **Working Memory** — Ephemeral context & candidates
- **Evaluation** — Benchmark metrics
- **System Health** — Service & projection status
        """
    )

# ─── Home page ─────────────────────────────────────────────────────────────
st.title("⚙️ AegisOps")
st.subheader("Industrial AI Operational Memory Platform")

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
