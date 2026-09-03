"""System Health page."""
from __future__ import annotations

import streamlit as st

from ui.api_client import api_get
from ui.framework import fetch_runtime_health, render_page_header, render_sidebar
from ui.observability import as_table_rows, metric_status, metric_value_text

st.set_page_config(page_title="System Health — AegisOps", page_icon="🏥", layout="wide", initial_sidebar_state="expanded")
render_sidebar()
render_page_header(
    "System Health",
    "Runtime, canonical memory, ingestion, and AI observability with explicit metric status semantics.",
)

auto_refresh = st.toggle("Auto-refresh every 30s", value=False)
if auto_refresh:
    import time

    time.sleep(30)
    st.rerun()

services = fetch_runtime_health()
obs = api_get("/api/v1/system/observability") or {}

if isinstance(obs, dict) and "error" in obs:
    st.error(f"Unable to load observability metrics: {obs['error']}")
    st.stop()

api_runtime = obs.get("api_runtime", {}) if isinstance(obs, dict) else {}
canonical = obs.get("canonical_memory", {}) if isinstance(obs, dict) else {}
scalar = obs.get("scalar_sensor_ingestion", {}) if isinstance(obs, dict) else {}
vision = obs.get("vision_pipeline", {}) if isinstance(obs, dict) else {}
llm = obs.get("llm", {}) if isinstance(obs, dict) else {}
agents = obs.get("agents_tools", {}) if isinstance(obs, dict) else {}

st.subheader("Service Status")
service_rows = []
for service_name in ["api", "postgres", "qdrant", "neo4j", "llm"]:
    state = str(services.get(service_name, {}).get("status", "unknown"))
    detail = (
        services.get(service_name, {}).get("error")
        or services.get(service_name, {}).get("uri")
        or services.get(service_name, {}).get("url")
        or ""
    )
    service_rows.append(
        {
            "Service": service_name.upper(),
            "Status": state,
            "Detail": detail,
        }
    )
st.dataframe(service_rows, use_container_width=True, hide_index=True)

runtime_tab, canonical_tab, scalar_tab, vision_tab, llm_tab = st.tabs(
    ["API / Runtime", "Canonical Memory", "Scalar / Sensor Ingestion", "Vision Pipeline", "LLM + Agents"]
)

with runtime_tab:
    key_metrics = [
        "requests_per_sec",
        "error_rate",
        "request_latency_p50",
        "request_latency_p95",
        "concurrent_requests",
        "db_connection_state",
    ]
    cols = st.columns(3)
    for idx, metric_name in enumerate(key_metrics):
        metric = api_runtime.get(metric_name, {})
        cols[idx % 3].metric(
            metric_name.replace("_", " ").title(),
            metric_value_text(metric),
            metric_status(metric),
        )

    if "cpu_utilization" in api_runtime and "memory_utilization" in api_runtime:
        c1, c2 = st.columns(2)
        c1.metric("CPU", metric_value_text(api_runtime["cpu_utilization"]), metric_status(api_runtime["cpu_utilization"]))
        c2.metric("Memory", metric_value_text(api_runtime["memory_utilization"]), metric_status(api_runtime["memory_utilization"]))

    st.dataframe(as_table_rows(api_runtime), use_container_width=True, hide_index=True)

with canonical_tab:
    key_metrics = [
        "total_canonical_records",
        "records_ingested",
        "ingestion_throughput",
        "write_latency_p50",
        "write_latency_p95",
        "failed_writes",
        "duplicate_or_rejected",
    ]
    cols = st.columns(3)
    for idx, metric_name in enumerate(key_metrics):
        metric = canonical.get(metric_name, {})
        cols[idx % 3].metric(
            metric_name.replace("_", " ").title(),
            metric_value_text(metric),
            metric_status(metric),
        )
    st.dataframe(as_table_rows(canonical), use_container_width=True, hide_index=True)

with scalar_tab:
    st.caption("Scalar / Sensor Ingestion")
    st.dataframe(as_table_rows(scalar), use_container_width=True, hide_index=True)

with vision_tab:
    st.caption("Vision ingestion and inference status")
    st.dataframe(as_table_rows(vision), use_container_width=True, hide_index=True)

with llm_tab:
    st.subheader("LLM Runtime")
    st.dataframe(as_table_rows(llm), use_container_width=True, hide_index=True)

    st.subheader("Agents / Tools")
    st.dataframe(as_table_rows(agents), use_container_width=True, hide_index=True)
