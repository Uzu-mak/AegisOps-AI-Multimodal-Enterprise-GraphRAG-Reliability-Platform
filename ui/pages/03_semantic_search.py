"""Semantic Search page."""
import streamlit as st
from ui.api_client import api_post

st.set_page_config(page_title="Semantic Search — AegisOps", page_icon="🔍", layout="wide")
st.title("🔍 Semantic Search")
st.caption("Vector similarity search over canonical operational memory via Qdrant.")

query = st.text_input("Enter search query", placeholder="pump vibration elevated at facility west")
limit = st.slider("Max results", 1, 20, 10)

if st.button("Search", type="primary") and query:
    with st.spinner("Searching..."):
        result = api_post("/api/v1/search/semantic", {"query": query, "limit": limit})

    if result and "error" not in result:
        results = result.get("results", [])
        st.success(f"Found {len(results)} results via semantic search")

        for i, r in enumerate(results, 1):
            score = r.get("semantic_score")
            title = r.get("title") or "(no title)"
            with st.expander(
                f"#{i} — {title} "
                f"[{r.get('memory_type', '')}] "
                f"score={score:.3f}" if score else f"#{i} — {title}"
            ):
                c1, c2, c3 = st.columns(3)
                c1.metric("Status", r.get("status") or "—")
                c2.metric("Confidence", f"{r.get('confidence', 0):.0%}" if r.get("confidence") else "—")
                c3.metric("Asset", r.get("asset_id") or "—")
                st.markdown(f"**Content:** {r.get('content_preview') or ''}")
                st.caption(f"Memory ID: `{r.get('memory_id', '')}`")
    else:
        st.warning("No results or search unavailable.")
        if result:
            st.error(result.get("error", "Unknown error"))
