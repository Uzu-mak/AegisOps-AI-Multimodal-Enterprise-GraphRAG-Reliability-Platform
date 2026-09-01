"""System Health page."""
import streamlit as st
from ui.api_client import api_get
from ui.framework import (
    fetch_runtime_health,
    render_health_cards,
    render_page_header,
    render_sidebar,
)

st.set_page_config(page_title="System Health — AegisOps", page_icon="🏥", layout="wide")
render_sidebar()
render_page_header("System & Projection Health")

auto_refresh = st.toggle("Auto-refresh every 30s", value=False)
if auto_refresh:
    import time
    time.sleep(30)
    st.rerun()

# Services
services = fetch_runtime_health()

st.subheader("Service Status")
render_health_cards(
    {k: services.get(k, {"status": "unknown"}) for k in ["api", "postgres", "qdrant", "neo4j", "llm"]}
)

postgres_status = str(services.get("postgres", {}).get("status", "unknown"))
if postgres_status not in {"healthy", "degraded"}:
    st.error("Canonical PostgreSQL store is unavailable. CRUD operations may fail.")

if str(services.get("qdrant", {}).get("status", "unknown")) not in {"healthy", "degraded"}:
    st.warning("Qdrant projection is unavailable. Semantic capabilities are degraded/unavailable.")

if str(services.get("neo4j", {}).get("status", "unknown")) not in {"healthy", "degraded"}:
    st.warning("Neo4j projection is unavailable. Graph capabilities are degraded/unavailable.")

st.divider()

# Outbox
st.subheader("Projection Outbox")
st.caption(
    "The outbox ensures Qdrant and Neo4j projections eventually complete "
    "even after transient failures. PostgreSQL remains canonical regardless."
)

outbox = api_get("/api/v1/system/outbox-stats") or {}
events = outbox.get("events", [])

if events:
    import pandas as pd
    df = pd.DataFrame(events)
    st.dataframe(df, use_container_width=True, hide_index=True)

    total = sum(e.get("count", 0) for e in events)
    pending = sum(e.get("count", 0) for e in events if e.get("status") == "pending")
    failed = sum(e.get("count", 0) for e in events if e.get("status") == "failed")
    completed = sum(e.get("count", 0) for e in events if e.get("status") == "completed")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Events", total)
    c2.metric("✅ Completed", completed)
    c3.metric("⏳ Pending", pending)
    c4.metric("❌ Failed", failed)
else:
    st.info("No outbox events found. The outbox table may not exist yet (run Alembic migrations).")

st.divider()

# LLM config
st.subheader("LLM Provider Configuration")
llm = services.get("llm", {})
if llm:
    c1, c2, c3 = st.columns(3)
    c1.metric("Provider", llm.get("provider", "—"))
    c2.metric("Model", llm.get("model", "—"))
    c3.metric("API Key Set", "✅ Yes" if llm.get("api_key_set") else "❌ No (test mode)")

    if not llm.get("api_key_set"):
        st.warning(
            "Running in deterministic test mode. "
            "Set `OPENAI_API_KEY=<key>` and `LLM_PROVIDER=openai` in `.env` "
            "for real LLM responses."
        )
