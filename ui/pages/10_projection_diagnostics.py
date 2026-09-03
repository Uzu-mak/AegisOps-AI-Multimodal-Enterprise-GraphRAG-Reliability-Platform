"""Projection Diagnostics page."""
from __future__ import annotations

import streamlit as st

from ui.api_client import api_get
from ui.framework import render_page_header, render_sidebar
from ui.observability import as_table_rows, metric_status, metric_value_text

st.set_page_config(page_title="Projection Diagnostics — AegisOps", page_icon="🧪", layout="wide", initial_sidebar_state="expanded")
render_sidebar()
render_page_header(
    "Projection Diagnostics",
    "Outbox/Kafka, Qdrant, and Neo4j projection scale and reliability metrics.",
)

metrics = api_get("/api/v1/system/projection-metrics") or {}
if isinstance(metrics, dict) and "error" in metrics:
    st.error(f"Unable to load projection metrics: {metrics['error']}")
    st.stop()

kafka_outbox = metrics.get("kafka_outbox", {}) if isinstance(metrics, dict) else {}
qdrant = metrics.get("qdrant", {}) if isinstance(metrics, dict) else {}
neo4j = metrics.get("neo4j", {}) if isinstance(metrics, dict) else {}

outbox_tab, qdrant_tab, neo4j_tab, raw_tab = st.tabs(["Kafka / Outbox", "Qdrant", "Neo4j", "Raw Payload"])

with outbox_tab:
    key = [
        "pending_outbox_events",
        "published_events",
        "failed_publication_attempts",
        "retry_count",
        "oldest_pending_event_age",
        "publication_throughput",
        "kafka_broker_health",
        "topic",
        "partition_count",
        "consumer_lag",
    ]
    cols = st.columns(3)
    for idx, metric_name in enumerate(key):
        metric = kafka_outbox.get(metric_name, {})
        cols[idx % 3].metric(
            metric_name.replace("_", " ").title(),
            metric_value_text(metric),
            metric_status(metric),
        )
    st.dataframe(as_table_rows(kafka_outbox), use_container_width=True, hide_index=True)

with qdrant_tab:
    key = [
        "projected_memories",
        "pending_projection_count",
        "failed_projections",
        "projection_lag",
        "indexing_throughput",
        "semantic_query_latency_p50",
        "semantic_query_latency_p95",
        "recall_at_5",
        "recall_at_10",
    ]
    cols = st.columns(3)
    for idx, metric_name in enumerate(key):
        metric = qdrant.get(metric_name, {})
        cols[idx % 3].metric(
            metric_name.replace("_", " ").title(),
            metric_value_text(metric),
            metric_status(metric),
        )
    st.dataframe(as_table_rows(qdrant), use_container_width=True, hide_index=True)

with neo4j_tab:
    key = [
        "projected_nodes_memories",
        "relationship_count",
        "pending_graph_projections",
        "failed_graph_projections",
        "projection_lag",
        "traversal_latency_p50",
        "traversal_latency_p95",
    ]
    cols = st.columns(3)
    for idx, metric_name in enumerate(key):
        metric = neo4j.get(metric_name, {})
        cols[idx % 3].metric(
            metric_name.replace("_", " ").title(),
            metric_value_text(metric),
            metric_status(metric),
        )
    st.dataframe(as_table_rows(neo4j), use_container_width=True, hide_index=True)

with raw_tab:
    st.json(metrics)
