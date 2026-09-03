"""Evaluation Dashboard page."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from app.evaluation.metrics import citation_accuracy, groundedness_score, mean_reciprocal_rank, recall_at_k
from ui.api_client import api_post
from ui.framework import capability_available, fetch_runtime_health, render_page_header, render_sidebar, render_unavailable_state

st.set_page_config(page_title="Evaluation — AegisOps", page_icon="📈", layout="wide", initial_sidebar_state="expanded")
render_sidebar()
render_page_header(
    "Evaluation",
    "Retrieval, GraphRAG, and answer-quality metrics from actual evaluation runs only.",
)

services = fetch_runtime_health()
available, reason = capability_available(services, ["api"])
if not available:
    render_unavailable_state(reason)
    st.stop()

if "eval_cases" not in st.session_state:
    st.session_state.eval_cases = []
if "eval_run_rows" not in st.session_state:
    st.session_state.eval_run_rows = []
if "eval_answer_rows" not in st.session_state:
    st.session_state.eval_answer_rows = []

run_tab, results_tab, taxonomy_tab = st.tabs(["Run Evaluation", "Results", "Failure Taxonomy"])

with run_tab:
    st.subheader("Benchmark Cases")
    with st.form("add_eval_case"):
        question = st.text_input("Question")
        expected = st.text_input("Expected Memory IDs (comma-separated)")
        submitted = st.form_submit_button("Add Case")
        if submitted and question.strip():
            st.session_state.eval_cases.append(
                {
                    "question": question.strip(),
                    "expected_ids": [p.strip() for p in expected.split(",") if p.strip()],
                }
            )
            st.success("Case added.")

    if st.session_state.eval_cases:
        st.write(f"{len(st.session_state.eval_cases)} case(s) queued")

    modes = st.multiselect(
        "Retrieval modes",
        ["semantic", "graph", "hybrid"],
        default=["semantic", "graph", "hybrid"],
    )

    run_clicked = st.button("Run Evaluation", type="primary", disabled=not st.session_state.eval_cases or not modes)
    if run_clicked:
        retrieval_rows: list[dict[str, object]] = []
        answer_rows: list[dict[str, object]] = []

        total_ops = len(st.session_state.eval_cases) * max(1, len(modes))
        done = 0
        progress = st.progress(0.0)

        for case in st.session_state.eval_cases:
            expected_ids = case["expected_ids"]
            question_text = case["question"]

            for mode in modes:
                resp = api_post(
                    "/api/v1/search/hybrid",
                    {
                        "query": question_text,
                        "mode": mode,
                        "limit": 10,
                        "graph_hops": 2,
                    },
                )

                retrieved_ids: list[str] = []
                latency_ms: float | None = None
                if isinstance(resp, dict) and "results" in resp and isinstance(resp.get("results"), list):
                    retrieved_ids = [str(item.get("memory_id")) for item in resp["results"] if item.get("memory_id")]
                    raw_latency = resp.get("latency_ms")
                    latency_ms = float(raw_latency) if isinstance(raw_latency, (int, float)) else None

                retrieval_rows.append(
                    {
                        "question": question_text,
                        "mode": mode,
                        "recall@5": recall_at_k(retrieved_ids, expected_ids, 5),
                        "recall@10": recall_at_k(retrieved_ids, expected_ids, 10),
                        "mrr": mean_reciprocal_rank(retrieved_ids, expected_ids),
                        "retrieval_latency_ms": latency_ms,
                        "retrieved_count": len(retrieved_ids),
                    }
                )

                done += 1
                progress.progress(done / total_ops)

            rag_resp = api_post(
                "/api/v1/graphrag/query",
                {
                    "question": question_text,
                    "context_limit": 5,
                    "anchor_memory_id": None,
                },
            )
            if isinstance(rag_resp, dict) and "error" not in rag_resp:
                answer_text = str(rag_resp.get("answer", ""))
                evidence_count = int(rag_resp.get("evidence_count", 0) or 0)
                answer_rows.append(
                    {
                        "question": question_text,
                        "citation_accuracy": citation_accuracy(answer_text, evidence_count),
                        "grounding_rate": groundedness_score(answer_text),
                        "evidence_coverage": 1.0 if evidence_count > 0 else 0.0,
                        "retrieval_latency_ms": float(rag_resp.get("retrieval_latency_ms", 0) or 0),
                        "total_latency_ms": float(rag_resp.get("total_latency_ms", 0) or 0),
                        "model_name": rag_resp.get("model_name", "unknown"),
                        "is_synthetic": bool(rag_resp.get("is_synthetic_response", False)),
                    }
                )

        st.session_state.eval_run_rows = retrieval_rows
        st.session_state.eval_answer_rows = answer_rows
        st.success("Evaluation run completed.")

    if st.button("Clear Cases"):
        st.session_state.eval_cases = []
        st.rerun()

with results_tab:
    retrieval_rows = st.session_state.eval_run_rows
    answer_rows = st.session_state.eval_answer_rows

    if not retrieval_rows:
        st.info("Not evaluated yet. Run an evaluation to view metrics.")
    else:
        df = pd.DataFrame(retrieval_rows)
        st.subheader("Retrieval Metrics")
        st.dataframe(df, use_container_width=True, hide_index=True)

        grouped = df.groupby("mode").agg(
            mean_recall5=("recall@5", "mean"),
            mean_recall10=("recall@10", "mean"),
            mean_mrr=("mrr", "mean"),
            retrieval_p50=("retrieval_latency_ms", lambda s: float(s.dropna().quantile(0.5)) if not s.dropna().empty else None),
            retrieval_p95=("retrieval_latency_ms", lambda s: float(s.dropna().quantile(0.95)) if not s.dropna().empty else None),
        )
        st.dataframe(grouped.reset_index(), use_container_width=True, hide_index=True)

        c1, c2, c3 = st.columns(3)
        c1.metric("Recall@5", f"{df['recall@5'].mean():.3f}")
        c2.metric("Recall@10", f"{df['recall@10'].mean():.3f}")
        c3.metric("MRR", f"{df['mrr'].mean():.3f}")

        semantic_mrr = grouped.loc["semantic", "mean_mrr"] if "semantic" in grouped.index else None
        hybrid_mrr = grouped.loc["hybrid", "mean_mrr"] if "hybrid" in grouped.index else None
        if semantic_mrr is not None and hybrid_mrr is not None:
            improvement = hybrid_mrr - semantic_mrr
            st.metric("Hybrid Improvement over Semantic (MRR)", f"{improvement:+.3f}")
        else:
            st.info("Hybrid improvement over semantic baseline: Not evaluated")

    st.subheader("Answer Quality (GraphRAG)")
    if not answer_rows:
        st.info("Not evaluated yet. Run an evaluation to compute answer quality and end-to-end latency metrics.")
    else:
        answers_df = pd.DataFrame(answer_rows)
        st.dataframe(answers_df, use_container_width=True, hide_index=True)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Citation Accuracy", f"{answers_df['citation_accuracy'].mean():.3f}")
        c2.metric("Grounding Rate", f"{answers_df['grounding_rate'].mean():.3f}")
        c3.metric("Evidence Coverage", f"{answers_df['evidence_coverage'].mean():.3f}")
        c4.metric("Answer p50 latency", f"{answers_df['total_latency_ms'].quantile(0.5):.2f} ms")

        c5, c6 = st.columns(2)
        c5.metric("Answer p95 latency", f"{answers_df['total_latency_ms'].quantile(0.95):.2f} ms")
        c6.metric("Retrieval p95 latency", f"{answers_df['retrieval_latency_ms'].quantile(0.95):.2f} ms")

with taxonomy_tab:
    st.subheader("Failure Taxonomy")
    st.markdown(
        """
| Category | Description |
|---|---|
| retrieval_failure | No relevant memories retrieved |
| graph_traversal_failure | Neo4j traversal error |
| context_construction_failure | Evidence could not be assembled |
| reasoning_failure | LLM produced incoherent answer |
| unsupported_claim | Answer contains unsupported assertions |
| citation_failure | Invalid or missing citations |
| incomplete_answer | Answer does not address the question |
| provider_failure | LLM or service error |
| no_failure | Evaluation passed |
        """
    )
