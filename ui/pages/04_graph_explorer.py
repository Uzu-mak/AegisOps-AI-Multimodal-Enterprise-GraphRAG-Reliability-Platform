"""Graph Explorer page."""
import streamlit as st
from ui.api_client import api_get, api_post

st.set_page_config(page_title="Graph Explorer — AegisOps", page_icon="🕸️", layout="wide")
st.title("🕸️ Graph Explorer")
st.caption("Explore relationship connections between operational memories via Neo4j.")

st.info(
    "The graph projection stores deterministic relationships derived from canonical "
    "PostgreSQL fields (asset, component, incident, facility, team, source). "
    "No causal or inferred edges are present in Phase 3."
)

memory_id = st.text_input(
    "Memory ID", placeholder="Paste a canonical memory UUID"
)
max_hops = st.select_slider("Max hops", options=[1, 2, 3, 4, 5], value=2)
limit = st.slider("Max related memories", 5, 100, 20)

if st.button("Explore Connections", type="primary") and memory_id:
    with st.spinner("Traversing graph..."):
        result = api_post(
            "/api/v1/search/graph-related",
            {"memory_id": memory_id, "max_hops": max_hops, "limit": limit},
        )

    if result and "error" not in result:
        related_ids = result.get("related_memory_ids", [])
        st.success(
            f"Found {len(related_ids)} related memories "
            f"(max_hops={max_hops})"
        )

        if related_ids:
            col1, col2 = st.columns([1, 2])
            with col1:
                st.subheader("Related Memory IDs")
                for rid in related_ids:
                    st.code(rid, language=None)

            with col2:
                st.subheader("Related Memory Details")
                # Fetch each memory and display
                for rid in related_ids[:10]:  # Cap display at 10
                    detail = api_get(f"/api/v1/memories/{rid}")
                    if detail and "error" not in detail:
                        with st.expander(
                            f"🔗 {detail.get('title', 'Untitled')} — {detail.get('memory_type', '')}"
                        ):
                            c1, c2 = st.columns(2)
                            c1.metric("Status", detail.get("status", ""))
                            c2.metric("Asset", detail.get("asset_id") or "—")
                            st.caption(detail.get("content", "")[:300])
        else:
            st.info("No connected memories found in the graph for this memory ID.")
    else:
        if result:
            st.error(result.get("error") or result.get("detail", "Graph unavailable"))
        else:
            st.error("No response from API")
