"""Working Memory & Agent Trace page."""
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
    render_unavailable_state,
)
from ui.working_memory_payload import build_promotion_payload

st.set_page_config(page_title="Working Memory — AegisOps", page_icon="🧩", layout="wide")
render_sidebar()
render_page_header(
    "Working Memory",
    "Working memory is ephemeral context for the current session. "
    "It is NOT automatically promoted to long-term PostgreSQL memory.",
)

services = fetch_runtime_health()
render_health_cards(
    {k: services.get(k, {"status": "unknown"}) for k in ["api", "postgres", "llm"]}
)

available, reason = capability_available(services, ["api", "postgres"])
if not available:
    render_unavailable_state(reason)
    st.stop()

st.info(
    "**Architecture Note:** Working memory holds temporary observations, retrieved "
    "evidence, tool outputs, and hypotheses. Promotion to long-term memory is an "
    "explicit decision using a MemoryCandidate + PromotionPolicy."
)

st.warning("No autonomous agent runtime is implemented in this page; query actions call backend endpoints directly.")

# Session-state backed working memory simulation
if "working_memory" not in st.session_state:
    st.session_state.working_memory = []
if "agent_traces" not in st.session_state:
    st.session_state.agent_traces = []

tab_wm, tab_agent, tab_promote = st.tabs(
    ["Working Memory", "Assisted Query Log", "Promote to Long-term Memory"]
)

with tab_wm:
    st.subheader("Current Working Memory")

    with st.form("add_observation"):
        obs_type = st.selectbox(
            "Item Type",
            ["observation", "hypothesis", "retrieved_evidence", "tool_output", "user_input"],
        )
        obs_content = st.text_area("Content", height=80)
        obs_source = st.text_input("Source")
        confidence = st.slider("Confidence", 0.0, 1.0, 0.7)
        importance = st.slider("Importance", 0.0, 1.0, 0.6)
        submitted = st.form_submit_button("Add to Working Memory")
        if submitted and obs_content:
            st.session_state.working_memory.append({
                "type": obs_type,
                "content": obs_content,
                "source": obs_source,
                "confidence": confidence,
                "importance": importance,
            })
            st.success("Added to working memory.")

    if st.session_state.working_memory:
        st.write(f"**{len(st.session_state.working_memory)} items** in working memory")
        for i, item in enumerate(reversed(st.session_state.working_memory)):
            with st.expander(f"[{item['type']}] {item['content'][:80]}"):
                c1, c2 = st.columns(2)
                c1.metric("Confidence", f"{item['confidence']:.0%}")
                c2.metric("Importance", f"{item['importance']:.0%}")
                st.write(item["content"])

        if st.button("Clear Working Memory"):
            st.session_state.working_memory = []
            st.rerun()
    else:
        st.info("Working memory is empty. Add observations above.")

with tab_agent:
    st.subheader("Run Assisted Query")
    task = st.text_input(
        "Task / Question",
        placeholder="Diagnose the root cause of elevated vibration on pump P-102",
    )
    anchor = st.text_input("Anchor Memory ID (optional)")

    if st.button("Run Query", type="primary") and task:
        with render_loading("Running backend query..."):
            result = api_post(
                "/api/v1/graphrag/query",
                {
                    "question": task,
                    "anchor_memory_id": anchor or None,
                    "context_limit": 5,
                },
            )

        if result and "error" not in result:
            st.session_state.agent_traces.append({
                "task": task,
                "answer": result.get("answer", ""),
                "evidence_count": result.get("evidence_count", 0),
                "latency_ms": result.get("total_latency_ms", 0),
                "model": result.get("model_name", ""),
                "is_synthetic": result.get("is_synthetic_response", True),
            })
            st.success("Query complete.")

    if st.session_state.agent_traces:
        st.subheader("Recent Query Logs")
        for trace in reversed(st.session_state.agent_traces[-5:]):
            with st.expander(f"{trace['task'][:80]}"):
                if trace["is_synthetic"]:
                    st.warning("⚠️ Synthetic response (test provider)")
                st.markdown(trace["answer"])
                c1, c2, c3 = st.columns(3)
                c1.metric("Evidence", trace["evidence_count"])
                c2.metric("Latency", f"{trace['latency_ms']:.0f}ms")
                c3.metric("Model", trace["model"])

with tab_promote:
    st.subheader("Promote to Long-term Memory")
    st.info(
        "A MemoryCandidate must pass a PromotionPolicy (confidence + importance thresholds) "
        "before it is written to PostgreSQL canonical memory."
    )

    items_with_min = [
        item for item in st.session_state.working_memory
        if item["confidence"] >= 0.6 and item["importance"] >= 0.4
        and len(item["content"].strip()) > 10
    ]

    if not items_with_min:
        st.info(
            "No promotable candidates in working memory. "
            "Add items with confidence ≥ 0.6 and importance ≥ 0.4."
        )
    else:
        st.success(f"{len(items_with_min)} candidates eligible for promotion.")
        for i, item in enumerate(items_with_min):
            with st.expander(f"Candidate {i+1}: {item['content'][:80]}"):
                with st.form(f"promote_{i}"):
                    title = st.text_input("Title *", key=f"ptitle_{i}")
                    mem_type = st.selectbox(
                        "Memory Type", ["observation", "diagnosis", "recommendation"],
                        key=f"pmtype_{i}",
                    )
                    asset_id = st.text_input("Asset ID", key=f"passet_{i}")
                    if st.form_submit_button("Promote to Long-term Memory"):
                        if not title.strip():
                            st.error("Title required.")
                        else:
                            result = api_post(
                                "/api/v1/memories",
                                build_promotion_payload(
                                    memory_type=mem_type,
                                    title=title,
                                    content=item["content"],
                                    source_type=item.get("source") or "operator",
                                    asset_id=asset_id or None,
                                    confidence=item["confidence"],
                                    importance=item["importance"],
                                ),
                            )
                            if result and "id" in result:
                                st.success(f"✅ Promoted to memory `{result['id']}`")
                            else:
                                render_error_state("Promotion failed.")
