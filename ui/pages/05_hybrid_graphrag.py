"""Ask AegisOps page."""
from __future__ import annotations

from collections import Counter

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
from ui.operations_catalog import format_memory_type, format_status

st.set_page_config(page_title="Ask AegisOps — AegisOps", page_icon="🧠", layout="wide", initial_sidebar_state="expanded")
render_sidebar()
render_page_header(
    "Ask AegisOps",
    "Natural-language operational questions with answer, recommended checks, evidence, similar incidents, provenance, and confidence.",
)

services = fetch_runtime_health()
render_dependency_notice(services, ["api", "postgres", "qdrant", "neo4j", "llm"])

available, reason = capability_available(services, ["api"])
if not available:
    render_unavailable_state(reason)
    st.stop()

question = st.text_area(
    "Your question",
    placeholder="What is the most likely cause of repeated vibration on pump P-102?",
    height=120,
)

query_ready = bool(question.strip())
if st.button("Ask AegisOps", type="primary", disabled=not query_ready):
    with render_loading("Analyzing question..."):
        answer_result = api_post(
            "/api/v1/graphrag/query",
            {
                "question": question,
                "context_limit": 5,
            },
        )
        similar_result = api_post(
            "/api/v1/search/hybrid",
            {
                "query": question,
                "mode": "hybrid",
                "limit": 5,
                "graph_hops": 2,
            },
        )

    if answer_result and "error" not in answer_result:
        st.session_state.ask_answer = answer_result
        st.session_state.ask_similar = similar_result if isinstance(similar_result, dict) and "error" not in similar_result else {}
        st.success("Answer ready.")
    else:
        render_error_state("AegisOps query failed.")

answer = st.session_state.get("ask_answer", {})
similar = st.session_state.get("ask_similar", {})

if answer:
    st.divider()
    st.subheader("Answer")
    st.markdown(answer.get("answer", ""))

    evidence = answer.get("evidence", [])
    evidence_confidence = [item.get("confidence") for item in evidence if isinstance(item.get("confidence"), (int, float))]
    confidence_value = sum(evidence_confidence) / len(evidence_confidence) if evidence_confidence else None

    metrics = st.columns(3)
    metrics[0].metric("Evidence Items", answer.get("evidence_count", len(evidence)))
    metrics[1].metric("Confidence", f"{confidence_value:.0%}" if confidence_value is not None else "—")
    metrics[2].metric("Provenance", answer.get("model_name", "—"))

    st.subheader("Recommended Checks")
    if evidence:
        for item in evidence[:3]:
            title = item.get("title") or format_memory_type(item.get("memory_type"))
            summary = (item.get("content_preview") or item.get("content") or "")[:140]
            st.write(f"- {title}: {summary}" if summary else f"- {title}")
    else:
        st.info("No recommended checks are available yet.")

    st.subheader("Evidence")
    if evidence:
        for item in evidence:
            with st.expander(f"{item.get('title', 'Untitled')} [{format_memory_type(item.get('memory_type'))}]"):
                cols = st.columns(3)
                cols[0].metric("Status", status_badge(item.get("status", "unknown")))
                cols[1].metric("Asset / Equipment", item.get("asset_id") or item.get("facility_id") or "—")
                cols[2].metric("Confidence", f"{float(item.get('confidence', 0) or 0):.0%}")
                st.markdown(item.get("content_preview") or item.get("content") or "")
    else:
        st.info("No evidence has been retrieved yet.")

    st.subheader("Similar Incidents")
    similar_results = similar.get("results", []) if isinstance(similar, dict) else []
    if similar_results:
        table_rows = []
        for item in similar_results:
            table_rows.append(
                {
                    "Title": item.get("title") or "Untitled",
                    "Type": format_memory_type(item.get("memory_type")),
                    "Status": format_status(item.get("status")),
                    "Asset": item.get("asset_id") or "—",
                    "Confidence": f"{float(item.get('confidence', 0) or 0):.0%}",
                    "Summary": (item.get("content_preview") or "")[:160],
                }
            )
        st.dataframe(table_rows, use_container_width=True, hide_index=True)
    else:
        st.info("No similar incidents have been found yet.")

    with st.expander("Technical Details"):
        st.json(
            {
                "answer_metadata": {
                    "question": question,
                    "evidence_count": answer.get("evidence_count", 0),
                    "retrieval_mode": answer.get("retrieval_mode"),
                    "is_synthetic_response": answer.get("is_synthetic_response"),
                    "total_latency_ms": answer.get("total_latency_ms"),
                },
                "similar_request": {
                    "query": question,
                    "mode": "hybrid",
                    "graph_hops": 2,
                },
            }
        )
