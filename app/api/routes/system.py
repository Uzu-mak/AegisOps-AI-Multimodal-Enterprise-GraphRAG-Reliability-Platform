"""System health and observability endpoints."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter
from sqlalchemy import func, select

import app.core.config as core_config
import app.db.session as db_session
from app.db.models.memory import MemoryRecord
from app.observability.metrics import MetricStatus, metric_value, metrics_collector
from app.outbox.models import ProjectionOutboxEvent, ProjectionStatus

router = APIRouter(prefix="/api/v1", tags=["system"])


class _KafkaDisabled(Exception):
    """Kafka integration stream is switched off by configuration."""


def _collect_service_health() -> dict[str, dict[str, Any]]:
    from app.graphrag.providers import llm_health_from_settings

    settings = core_config.get_settings()
    health: dict[str, dict[str, Any]] = {}

    # PostgreSQL
    try:
        from sqlalchemy import text

        with db_session.SessionLocal() as session:
            session.execute(text("SELECT 1"))
        health["postgres"] = {"status": "healthy", "host": "postgres"}
    except Exception as exc:
        health["postgres"] = {"status": "unhealthy", "error": str(exc)}

    # Qdrant / Neo4j — cached clients, short timeouts, fail fast during cool-down
    from app.core.connections import get_connections

    conns = get_connections()
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=2) as pool:
        probes = {name: pool.submit(conns.probe, name) for name in ("qdrant", "neo4j")}
        health.update({name: future.result() for name, future in probes.items()})

    llm_health = llm_health_from_settings(settings)
    health["llm"] = {
        "status": llm_health.status.value,
        "provider": llm_health.provider,
        "model": llm_health.model,
        "api_key_set": llm_health.api_key_set,
    }
    if llm_health.error:
        health["llm"]["error"] = llm_health.error
    try:
        from app.graphrag.providers import create_llm_provider

        active_model = create_llm_provider(settings).get_model_name()
    except Exception:  # noqa: BLE001
        active_model = None
    health["llm"]["active_model"] = active_model
    health["llm"]["synthetic"] = bool(active_model and "deterministic-test" in active_model)

    return health


def _overall_status(health: dict[str, dict[str, Any]]) -> str:
    return "healthy" if all(v.get("status") == "healthy" for v in health.values()) else "degraded"


def _status_metric_for_optional(value: Any, unit: str | None = None, detail: str = "Not instrumented") -> dict[str, Any]:
    if value is None:
        return metric_value(status=MetricStatus.NOT_INSTRUMENTED, value=None, unit=unit, detail=detail)
    return metric_value(status=MetricStatus.AVAILABLE, value=value, unit=unit)


def _not_connected(detail: str = "Not connected") -> dict[str, Any]:
    return metric_value(status=MetricStatus.NOT_CONNECTED, value=None, detail=detail)


def _not_instrumented(detail: str = "Not instrumented") -> dict[str, Any]:
    return metric_value(status=MetricStatus.NOT_INSTRUMENTED, value=None, detail=detail)


@router.get("/system/health")
def system_health() -> dict:
    """Check health of all AegisOps services."""
    health = _collect_service_health()
    from app.api.deps import get_embedding_provider

    embedder = get_embedding_provider()
    return {
        "status": _overall_status(health),
        "services": health,
        "integrations": {
            "kafka_enabled": bool(getattr(core_config.get_settings(), "KAFKA_ENABLED", False)),
        },
        "embedding_provider": {
            "name": type(embedder).__name__,
            "dimension": embedder.get_dimension(),
            "semantic": type(embedder).__name__ == "OpenAIEmbedding",
        },
    }


@router.get("/system/memory-stats")
def memory_stats() -> dict:
    """Return counts of memories by type and status."""
    try:
        with db_session.SessionLocal() as session:
            total = session.scalar(select(func.count(MemoryRecord.id)))

            by_status = session.execute(
                select(MemoryRecord.status, func.count(MemoryRecord.id)).group_by(MemoryRecord.status)
            ).all()

            by_type = session.execute(
                select(MemoryRecord.memory_type, func.count(MemoryRecord.id)).group_by(MemoryRecord.memory_type)
            ).all()

        return {
            "total": total,
            "by_status": {row[0]: row[1] for row in by_status},
            "by_type": {row[0]: row[1] for row in by_type},
        }
    except Exception as exc:
        return {"error": str(exc)}


@router.get("/system/outbox-stats")
def outbox_stats() -> dict:
    """Return projection outbox status counts."""
    try:
        with db_session.SessionLocal() as session:
            rows = session.execute(
                select(
                    ProjectionOutboxEvent.status,
                    ProjectionOutboxEvent.projection_type,
                    func.count(ProjectionOutboxEvent.id).label("count"),
                ).group_by(
                    ProjectionOutboxEvent.status,
                    ProjectionOutboxEvent.projection_type,
                )
            ).all()

        events = [
            {"status": r.status, "projection_type": r.projection_type, "count": r.count}
            for r in rows
        ]
        return {
            "events": events,
            "summary": {
                "pending": sum(e["count"] for e in events if e["status"] in {"pending", "retrying", "processing"}),
                "failed": sum(e["count"] for e in events if e["status"] == "failed"),
                "completed": sum(e["count"] for e in events if e["status"] == "completed"),
            },
        }
    except Exception as exc:
        return {"error": str(exc)}


@router.get("/system/observability")
def observability_metrics() -> dict[str, Any]:
    """Platform/runtime observability metrics with explicit status semantics."""
    settings = core_config.get_settings()
    services = _collect_service_health()

    runtime = metrics_collector.runtime_snapshot(window_seconds=300)
    write = metrics_collector.canonical_write_snapshot(window_seconds=900)
    retrieval = metrics_collector.retrieval_snapshot(window_seconds=900)
    llm_runtime = metrics_collector.llm_snapshot(window_seconds=900)
    investigations = metrics_collector.investigation_snapshot(window_seconds=900)

    cpu_metric = _not_instrumented("Not instrumented")
    mem_metric = _not_instrumented("Not instrumented")
    try:
        import psutil  # type: ignore

        cpu_metric = metric_value(status=MetricStatus.AVAILABLE, value=psutil.cpu_percent(interval=0.0), unit="percent")
        mem_metric = metric_value(status=MetricStatus.AVAILABLE, value=psutil.virtual_memory().percent, unit="percent")
    except Exception:
        pass

    db_state = services.get("postgres", {}).get("status", "unknown")
    if db_state in {"healthy", "degraded"}:
        db_connection_state = metric_value(status=MetricStatus.AVAILABLE, value=db_state)
    elif db_state == "unhealthy":
        db_connection_state = metric_value(
            status=MetricStatus.DEGRADED,
            value=None,
            detail=services.get("postgres", {}).get("error", "Database is unhealthy"),
        )
    else:
        db_connection_state = _not_connected("Database is unavailable")

    canonical_total = None
    ingestion_throughput = None
    try:
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(minutes=15)
        with db_session.SessionLocal() as session:
            canonical_total = session.scalar(select(func.count(MemoryRecord.id)))
            ingested_recent = session.scalar(
                select(func.count(MemoryRecord.id)).where(MemoryRecord.created_at >= cutoff)
            )
        ingestion_throughput = (float(ingested_recent or 0) / (15 * 60))
    except Exception:
        canonical_total = None
        ingestion_throughput = None

    canonical_group = {
        "total_canonical_records": _status_metric_for_optional(canonical_total, unit="records", detail="Not connected"),
        "records_ingested": _status_metric_for_optional(canonical_total, unit="records", detail="Not connected"),
        "ingestion_throughput": _status_metric_for_optional(ingestion_throughput, unit="events_per_sec", detail="Not instrumented"),
        "write_latency_p50": _status_metric_for_optional(write.get("write_p50_ms"), unit="ms", detail="Not instrumented"),
        "write_latency_p95": _status_metric_for_optional(write.get("write_p95_ms"), unit="ms", detail="Not instrumented"),
        "failed_writes": (
            metric_value(status=MetricStatus.AVAILABLE, value=write["failed_writes"], unit="events")
            if write.get("samples", 0) > 0
            else _not_instrumented("Not instrumented")
        ),
        "duplicate_or_rejected": (
            metric_value(
                status=MetricStatus.AVAILABLE,
                value=(write["duplicate_writes"] + write["rejected_writes"]),
                unit="events",
            )
            if write.get("samples", 0) > 0
            else _not_instrumented("Not instrumented")
        ),
    }

    llm_group = {
        "provider": metric_value(status=MetricStatus.AVAILABLE, value=services.get("llm", {}).get("provider", "unknown")),
        "model": metric_value(status=MetricStatus.AVAILABLE, value=services.get("llm", {}).get("model", settings.LLM_MODEL)),
        "request_count": _status_metric_for_optional(
            llm_runtime.get("request_count") if llm_runtime.get("request_count", 0) > 0 else None,
            unit="requests",
            detail="Not instrumented",
        ),
        "success_rate": _status_metric_for_optional(llm_runtime.get("success_rate"), unit="ratio", detail="Not instrumented"),
        "failure_rate": _status_metric_for_optional(llm_runtime.get("failure_rate"), unit="ratio", detail="Not instrumented"),
        "latency_p50": _status_metric_for_optional(llm_runtime.get("latency_p50_ms"), unit="ms", detail="Not instrumented"),
        "latency_p95": _status_metric_for_optional(llm_runtime.get("latency_p95_ms"), unit="ms", detail="Not instrumented"),
        "token_input": _status_metric_for_optional(
            llm_runtime.get("prompt_tokens") if llm_runtime.get("request_count", 0) > 0 else None,
            unit="tokens",
            detail="Not instrumented",
        ),
        "token_output": _status_metric_for_optional(
            llm_runtime.get("completion_tokens") if llm_runtime.get("request_count", 0) > 0 else None,
            unit="tokens",
            detail="Not instrumented",
        ),
        "estimated_cost_per_query": _not_instrumented("Pricing not configured"),
        "grounded_answer_rate": _not_instrumented("Not evaluated"),
    }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status_model": [s.value for s in MetricStatus],
        "api_runtime": {
            "requests_per_sec": metric_value(status=MetricStatus.AVAILABLE, value=runtime.get("requests_per_sec"), unit="req_per_sec"),
            "error_rate": _status_metric_for_optional(runtime.get("error_rate"), unit="ratio", detail="Not instrumented"),
            "request_latency_p50": _status_metric_for_optional(runtime.get("latency_p50_ms"), unit="ms", detail="Not instrumented"),
            "request_latency_p95": _status_metric_for_optional(runtime.get("latency_p95_ms"), unit="ms", detail="Not instrumented"),
            "concurrent_requests": metric_value(status=MetricStatus.AVAILABLE, value=runtime.get("concurrent_requests"), unit="requests"),
            "cpu_utilization": cpu_metric,
            "memory_utilization": mem_metric,
            "db_connection_state": db_connection_state,
        },
        "canonical_memory": canonical_group,
        "llm": llm_group,
        "investigations": {
            "investigations_run": metric_value(status=MetricStatus.AVAILABLE, value=investigations["investigations"], unit="runs"),
            "critic_supported_rate": _status_metric_for_optional(investigations["supported_rate"], unit="ratio", detail="No investigations yet"),
            "investigation_latency_p50": _status_metric_for_optional(investigations["latency_p50_ms"], unit="ms", detail="No investigations yet"),
            "findings_submitted": metric_value(status=MetricStatus.AVAILABLE, value=investigations["findings_submitted"], unit="findings"),
            "finding_acceptance_rate": _status_metric_for_optional(investigations["finding_acceptance_rate"], unit="ratio", detail="No findings submitted yet"),
        },
        "retrieval_runtime": retrieval,
    }


@router.get("/system/projection-metrics")
def projection_metrics() -> dict[str, Any]:
    """Projection and infrastructure metrics for Kafka/outbox/Qdrant/Neo4j."""
    settings = core_config.get_settings()
    services = _collect_service_health()
    retrieval = metrics_collector.retrieval_snapshot(window_seconds=900)

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=15)

    with db_session.SessionLocal() as session:
        pending_outbox = session.scalar(
            select(func.count(ProjectionOutboxEvent.id)).where(
                ProjectionOutboxEvent.status.in_(
                    [
                        ProjectionStatus.PENDING.value,
                        ProjectionStatus.RETRYING.value,
                        ProjectionStatus.PROCESSING.value,
                    ]
                )
            )
        )
        published_events = session.scalar(
            select(func.count(func.distinct(ProjectionOutboxEvent.event_id))).where(
                ProjectionOutboxEvent.kafka_published_at.is_not(None)
            )
        )
        kafka_failed_attempts = session.scalar(select(func.sum(ProjectionOutboxEvent.kafka_retry_count)))
        projection_retries = session.scalar(select(func.sum(ProjectionOutboxEvent.retry_count)))
        kafka_enabled = bool(getattr(settings, "KAFKA_ENABLED", False))
        oldest_pending = session.scalar(
            select(func.min(ProjectionOutboxEvent.occurred_at)).where(
                ProjectionOutboxEvent.kafka_published_at.is_(None)
                if kafka_enabled
                else ProjectionOutboxEvent.status.in_(
                    [ProjectionStatus.PENDING.value, ProjectionStatus.RETRYING.value, ProjectionStatus.PROCESSING.value]
                )
            )
        )
        published_recent = session.scalar(
            select(func.count(func.distinct(ProjectionOutboxEvent.event_id))).where(
                ProjectionOutboxEvent.kafka_published_at >= cutoff
            )
        )

        qdrant_pending = session.scalar(
            select(func.count(ProjectionOutboxEvent.id)).where(
                ProjectionOutboxEvent.projection_type == "qdrant",
                ProjectionOutboxEvent.status.in_(
                    [
                        ProjectionStatus.PENDING.value,
                        ProjectionStatus.RETRYING.value,
                        ProjectionStatus.PROCESSING.value,
                    ]
                ),
            )
        )
        qdrant_failed = session.scalar(
            select(func.count(ProjectionOutboxEvent.id)).where(
                ProjectionOutboxEvent.projection_type == "qdrant",
                ProjectionOutboxEvent.status == ProjectionStatus.FAILED.value,
            )
        )
        qdrant_oldest_pending = session.scalar(
            select(func.min(ProjectionOutboxEvent.occurred_at)).where(
                ProjectionOutboxEvent.projection_type == "qdrant",
                ProjectionOutboxEvent.status.in_(
                    [
                        ProjectionStatus.PENDING.value,
                        ProjectionStatus.RETRYING.value,
                        ProjectionStatus.PROCESSING.value,
                    ]
                ),
            )
        )
        qdrant_completed_recent = session.scalar(
            select(func.count(ProjectionOutboxEvent.id)).where(
                ProjectionOutboxEvent.projection_type == "qdrant",
                ProjectionOutboxEvent.completed_at >= cutoff,
            )
        )

        neo4j_pending = session.scalar(
            select(func.count(ProjectionOutboxEvent.id)).where(
                ProjectionOutboxEvent.projection_type == "neo4j",
                ProjectionOutboxEvent.status.in_(
                    [
                        ProjectionStatus.PENDING.value,
                        ProjectionStatus.RETRYING.value,
                        ProjectionStatus.PROCESSING.value,
                    ]
                ),
            )
        )
        neo4j_failed = session.scalar(
            select(func.count(ProjectionOutboxEvent.id)).where(
                ProjectionOutboxEvent.projection_type == "neo4j",
                ProjectionOutboxEvent.status == ProjectionStatus.FAILED.value,
            )
        )
        neo4j_oldest_pending = session.scalar(
            select(func.min(ProjectionOutboxEvent.occurred_at)).where(
                ProjectionOutboxEvent.projection_type == "neo4j",
                ProjectionOutboxEvent.status.in_(
                    [
                        ProjectionStatus.PENDING.value,
                        ProjectionStatus.RETRYING.value,
                        ProjectionStatus.PROCESSING.value,
                    ]
                ),
            )
        )

    oldest_pending_age = (now - oldest_pending).total_seconds() if oldest_pending else None
    qdrant_projection_lag = (now - qdrant_oldest_pending).total_seconds() if qdrant_oldest_pending else None
    neo4j_projection_lag = (now - neo4j_oldest_pending).total_seconds() if neo4j_oldest_pending else None

    kafka_health = _not_connected("Kafka broker unavailable")
    kafka_partitions = _not_connected("Kafka broker unavailable")
    try:
        if not kafka_enabled:
            raise _KafkaDisabled()
        from kafka import KafkaAdminClient

        timeout_ms = int(float(getattr(settings, "PROJECTION_CONNECT_TIMEOUT_SECONDS", 2)) * 1000)
        admin = KafkaAdminClient(
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            client_id="aegisops-health",
            request_timeout_ms=max(timeout_ms, 1000),
            api_version_auto_timeout_ms=max(timeout_ms, 1000),
        )
        topic_meta = admin.describe_topics([settings.KAFKA_PROJECTION_TOPIC])[0]
        kafka_health = metric_value(status=MetricStatus.AVAILABLE, value="healthy")
        kafka_partitions = metric_value(
            status=MetricStatus.AVAILABLE,
            value=len(topic_meta.get("partitions", [])),
            unit="partitions",
        )
        admin.close()
    except _KafkaDisabled:
        off = "Integration stream off (KAFKA_ENABLED=false); not required for projections"
        kafka_health = _not_instrumented(off)
        kafka_partitions = _not_instrumented(off)
    except Exception as exc:
        kafka_health = metric_value(status=MetricStatus.NOT_CONNECTED, value=None, detail=str(exc))

    qdrant_projected = _not_connected("Qdrant not connected")
    if services.get("qdrant", {}).get("status") in {"healthy", "degraded"}:
        try:
            from app.core.connections import get_connections

            client = get_connections().qdrant_client()
            if client is None:
                raise RuntimeError("Qdrant not connected")
            count_res = client.count(collection_name=settings.QDRANT_COLLECTION_NAME, exact=True)
            qdrant_projected = metric_value(status=MetricStatus.AVAILABLE, value=int(count_res.count), unit="records")
        except Exception as exc:
            qdrant_projected = metric_value(status=MetricStatus.DEGRADED, value=None, detail="Connected to Qdrant, but collection metrics are unavailable: " + type(exc).__name__)

    neo4j_nodes = _not_connected("Neo4j not connected")
    neo4j_relationships = _not_connected("Neo4j not connected")
    if services.get("neo4j", {}).get("status") in {"healthy", "degraded"}:
        try:
            from app.core.connections import get_connections

            driver = get_connections().neo4j_driver()
            if driver is None:
                raise RuntimeError("Neo4j not connected")
            with driver.session(database=settings.NEO4J_DATABASE) as neo_session:
                node_count = neo_session.run("MATCH (m:Memory) RETURN count(m) AS c").single()["c"]
                rel_count = neo_session.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
            neo4j_nodes = metric_value(status=MetricStatus.AVAILABLE, value=int(node_count), unit="nodes")
            neo4j_relationships = metric_value(status=MetricStatus.AVAILABLE, value=int(rel_count), unit="relationships")
        except Exception as exc:
            neo4j_nodes = metric_value(status=MetricStatus.NOT_CONNECTED, value=None, detail=str(exc))
            neo4j_relationships = metric_value(status=MetricStatus.NOT_CONNECTED, value=None, detail=str(exc))

    semantic_runtime = retrieval.get("by_mode", {}).get("semantic", {})

    return {
        "generated_at": now.isoformat(),
        "kafka_outbox": {
            "pending_outbox_events": metric_value(status=MetricStatus.AVAILABLE, value=int(pending_outbox or 0), unit="events"),
            "published_events": metric_value(status=MetricStatus.AVAILABLE, value=int(published_events or 0), unit="events")
            if kafka_enabled else _not_instrumented("Integration stream off (KAFKA_ENABLED=false)"),
            "failed_publication_attempts": metric_value(status=MetricStatus.AVAILABLE, value=int(kafka_failed_attempts or 0), unit="attempts")
            if kafka_enabled else _not_instrumented("Integration stream off (KAFKA_ENABLED=false)"),
            "retry_count": metric_value(status=MetricStatus.AVAILABLE, value=int(projection_retries or 0), unit="retries"),
            "oldest_pending_event_age": _status_metric_for_optional(oldest_pending_age, unit="seconds", detail="No pending events"),
            "publication_throughput": metric_value(
                status=MetricStatus.AVAILABLE,
                value=float((published_recent or 0) / (15 * 60)),
                unit="events_per_sec",
            ),
            "kafka_broker_health": kafka_health,
            "topic": metric_value(status=MetricStatus.AVAILABLE, value=settings.KAFKA_PROJECTION_TOPIC),
            "partition_count": kafka_partitions,
            "consumer_lag": metric_value(
                status=MetricStatus.NOT_INSTRUMENTED,
                value=None,
                detail="Not applicable — Kafka consumers not implemented; Kafka is the outbound stream for "
                "external systems, projections are applied from the PostgreSQL outbox by the projection worker",
            ),
        },
        "qdrant": {
            "projected_memories": qdrant_projected,
            "pending_projection_count": metric_value(status=MetricStatus.AVAILABLE, value=int(qdrant_pending or 0), unit="events"),
            "failed_projections": metric_value(status=MetricStatus.AVAILABLE, value=int(qdrant_failed or 0), unit="events"),
            "projection_lag": _status_metric_for_optional(qdrant_projection_lag, unit="seconds", detail="No pending projections"),
            "indexing_throughput": metric_value(
                status=MetricStatus.AVAILABLE,
                value=float((qdrant_completed_recent or 0) / (15 * 60)),
                unit="events_per_sec",
            ),
            "semantic_query_latency_p50": _status_metric_for_optional(semantic_runtime.get("latency_p50_ms"), unit="ms", detail="Not instrumented"),
            "semantic_query_latency_p95": _status_metric_for_optional(semantic_runtime.get("latency_p95_ms"), unit="ms", detail="Not instrumented"),
            "recall_at_5": _not_instrumented("Not evaluated"),
            "recall_at_10": _not_instrumented("Not evaluated"),
        },
        "neo4j": {
            "projected_nodes_memories": neo4j_nodes,
            "relationship_count": neo4j_relationships,
            "pending_graph_projections": metric_value(status=MetricStatus.AVAILABLE, value=int(neo4j_pending or 0), unit="events"),
            "failed_graph_projections": metric_value(status=MetricStatus.AVAILABLE, value=int(neo4j_failed or 0), unit="events"),
            "projection_lag": _status_metric_for_optional(neo4j_projection_lag, unit="seconds", detail="No pending graph projections"),
            "traversal_latency_p50": _status_metric_for_optional(retrieval.get("graph_latency_p50_ms"), unit="ms", detail="Not instrumented"),
            "traversal_latency_p95": _status_metric_for_optional(retrieval.get("graph_latency_p95_ms"), unit="ms", detail="Not instrumented"),
        },
    }
