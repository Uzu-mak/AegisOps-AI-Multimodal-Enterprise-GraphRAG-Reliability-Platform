"""Semantic Search page."""
import time

import streamlit as st
from ui.api_client import api_post
from ui.framework import (
    capability_available,
    fetch_runtime_health,
    render_error_state,
    render_health_cards,
    render_loading,
    render_page_header,
    render_sidebar,
    render_table,
    render_unavailable_state,
)

st.set_page_config(page_title="Semantic Search — AegisOps", page_icon="🔍", layout="wide")
render_sidebar()
render_page_header(
    "Semantic Search",
    "Vector similarity retrieval over canonical memories via Qdrant projection.",
)

services = fetch_runtime_health()
render_health_cards({k: services.get(k, {"status": "unknown"}) for k in ["api", "postgres", "qdrant"]})

available, reason = capability_available(services, ["api", "qdrant"])
if not available:
    render_unavailable_state(reason)
    st.stop()

query = st.text_input("Enter search query", placeholder="pump vibration elevated at facility west")
limit = st.slider("Max results", 1, 20, 10)

if st.button("Search", type="primary") and query:
    with render_loading("Searching..."):
        t0 = time.monotonic()
        result = api_post("/api/v1/search/semantic", {"query": query, "limit": limit})
        request_ms = (time.monotonic() - t0) * 1000

    if result and "error" not in result:
        results = result.get("results", [])
        latency_ms = result.get("latency_ms", request_ms)
        st.success(f"Found {len(results)} results via semantic search")
        st.metric("Search Latency", f"{latency_ms:.1f}ms")

        table_rows = [
            {
                "memory_id": r.get("memory_id", ""),
                "title": r.get("title") or "(no title)",
                "memory_type": r.get("memory_type") or "",
                "status": r.get("status") or "",
                "semantic_score": round(r.get("semantic_score"), 4)
                if isinstance(r.get("semantic_score"), (int, float))
                else "",
                "asset_id": r.get("asset_id") or "",
            }
            for r in results
        ]
        render_table(table_rows, empty_message="No semantic matches found.")

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
        if isinstance(result, dict) and result.get("detail"):
            render_error_state(str(result.get("detail")))
        else:
            render_error_state((result or {}).get("error", "Semantic search unavailable."))
