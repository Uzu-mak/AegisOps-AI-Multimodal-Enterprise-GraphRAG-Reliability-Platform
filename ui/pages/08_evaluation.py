"""Evaluation Dashboard page."""
import streamlit as st
import pandas as pd

st.set_page_config(page_title="Evaluation — AegisOps", page_icon="📈", layout="wide")
st.title("📈 Evaluation Dashboard")
st.caption(
    "Benchmark retrieval and GraphRAG quality. "
    "Only metrics from actual runs are reported — no fabricated numbers."
)

st.info(
    "The evaluation framework supports Recall@K, MRR, groundedness, and citation "
    "accuracy across semantic, graph, hybrid, and agentic retrieval modes. "
    "Configure benchmark cases in your evaluation scripts and results appear here."
)

tab_run, tab_results, tab_taxonomy = st.tabs(["Run Evaluation", "Results", "Failure Taxonomy"])

with tab_run:
    st.subheader("Quick Benchmark")
    st.markdown(
        "Enter benchmark cases below to evaluate retrieval quality. "
        "Each case should have a question and optionally expected memory IDs."
    )

    if "eval_cases" not in st.session_state:
        st.session_state.eval_cases = []
    if "eval_results" not in st.session_state:
        st.session_state.eval_results = []

    with st.form("add_eval_case"):
        case_q = st.text_input("Question")
        case_expected = st.text_input(
            "Expected Memory IDs (comma-separated, optional)"
        )
        if st.form_submit_button("Add Case"):
            if case_q:
                st.session_state.eval_cases.append({
                    "question": case_q,
                    "expected_ids": [
                        x.strip()
                        for x in case_expected.split(",")
                        if x.strip()
                    ],
                })
                st.success(f"Added case: {case_q[:60]}")

    if st.session_state.eval_cases:
        st.write(f"**{len(st.session_state.eval_cases)} evaluation cases queued**")

        mode = st.selectbox("Retrieval mode to evaluate", ["hybrid", "semantic", "graph"])

        if st.button("Run Evaluation", type="primary"):
            from ui.api_client import api_post
            results = []

            prog = st.progress(0)
            for i, case in enumerate(st.session_state.eval_cases):
                resp = api_post(
                    "/api/v1/search/hybrid",
                    {"query": case["question"], "mode": mode, "limit": 10},
                )
                retrieved = []
                if resp and "results" in resp:
                    retrieved = [r["memory_id"] for r in resp["results"]]

                from app.evaluation.metrics import recall_at_k, mean_reciprocal_rank, groundedness_score

                recall = recall_at_k(retrieved, case["expected_ids"], 5)
                mrr = mean_reciprocal_rank(retrieved, case["expected_ids"])
                results.append({
                    "question": case["question"][:60],
                    "retrieved_count": len(retrieved),
                    "recall@5": round(recall, 3),
                    "mrr": round(mrr, 3),
                    "success": recall > 0 or not case["expected_ids"],
                })
                prog.progress((i + 1) / len(st.session_state.eval_cases))

            st.session_state.eval_results = results
            st.success("Evaluation complete.")

        if st.button("Clear Cases"):
            st.session_state.eval_cases = []
            st.rerun()

with tab_results:
    st.subheader("Last Evaluation Results")
    if st.session_state.eval_results:
        df = pd.DataFrame(st.session_state.eval_results)
        st.dataframe(df, use_container_width=True, hide_index=True)

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Cases", len(df))
        c2.metric("Task Success", f"{df['success'].mean():.0%}")
        c3.metric("Mean Recall@5", f"{df['recall@5'].mean():.3f}")
        c4.metric("Mean MRR", f"{df['mrr'].mean():.3f}")
    else:
        st.info("No evaluation results yet. Run an evaluation from the 'Run Evaluation' tab.")

with tab_taxonomy:
    st.subheader("Failure Taxonomy")
    st.markdown("""
| Category | Description |
|---|---|
| `retrieval_failure` | No relevant memories retrieved |
| `graph_traversal_failure` | Neo4j traversal error |
| `context_construction_failure` | Evidence could not be assembled |
| `reasoning_failure` | LLM produced incoherent answer |
| `unsupported_claim` | Answer contains unsupported assertions |
| `citation_failure` | Invalid or missing citations |
| `incomplete_answer` | Answer does not address the question |
| `provider_failure` | LLM or service error |
| `no_failure` | Evaluation passed |
    """)
