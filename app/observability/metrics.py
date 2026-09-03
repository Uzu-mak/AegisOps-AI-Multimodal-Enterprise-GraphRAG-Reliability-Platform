from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from threading import Lock
from time import monotonic
from typing import Any


class MetricStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    NOT_INSTRUMENTED = "NOT_INSTRUMENTED"
    NOT_CONNECTED = "NOT_CONNECTED"
    DEGRADED = "DEGRADED"


@dataclass(frozen=True)
class MetricSample:
    ts: float
    value: float


@dataclass(frozen=True)
class RequestSample:
    ts: float
    latency_ms: float
    status_code: int


@dataclass(frozen=True)
class WriteSample:
    ts: float
    latency_ms: float
    outcome: str


@dataclass(frozen=True)
class RetrievalSample:
    ts: float
    mode: str
    latency_ms: float


@dataclass(frozen=True)
class GraphTraversalSample:
    ts: float
    latency_ms: float


@dataclass(frozen=True)
class LLMCallSample:
    ts: float
    provider: str
    model: str
    success: bool
    latency_ms: float
    prompt_tokens: int
    completion_tokens: int


class InProcessMetricsCollector:
    """Simple in-memory metrics collector for runtime/process-level observations."""

    def __init__(self, retention_seconds: int = 3600) -> None:
        self._retention_seconds = retention_seconds
        self._lock = Lock()

        self._request_samples: deque[RequestSample] = deque()
        self._write_samples: deque[WriteSample] = deque()
        self._retrieval_samples: deque[RetrievalSample] = deque()
        self._graph_traversal_samples: deque[GraphTraversalSample] = deque()
        self._graphrag_retrieval_samples: deque[MetricSample] = deque()
        self._graphrag_total_samples: deque[MetricSample] = deque()
        self._llm_samples: deque[LLMCallSample] = deque()

        self._inflight_requests = 0
        self._peak_inflight_requests = 0

    def _prune(self, now_ts: float) -> None:
        cutoff = now_ts - self._retention_seconds
        for queue in [
            self._request_samples,
            self._write_samples,
            self._retrieval_samples,
            self._graph_traversal_samples,
            self._graphrag_retrieval_samples,
            self._graphrag_total_samples,
            self._llm_samples,
        ]:
            while queue and queue[0].ts < cutoff:
                queue.popleft()

    def request_started(self) -> float:
        now_ts = monotonic()
        with self._lock:
            self._inflight_requests += 1
            if self._inflight_requests > self._peak_inflight_requests:
                self._peak_inflight_requests = self._inflight_requests
            self._prune(now_ts)
        return now_ts

    def request_finished(self, started_at: float, status_code: int) -> None:
        now_ts = monotonic()
        sample = RequestSample(
            ts=now_ts,
            latency_ms=(now_ts - started_at) * 1000,
            status_code=status_code,
        )
        with self._lock:
            self._request_samples.append(sample)
            self._inflight_requests = max(0, self._inflight_requests - 1)
            self._prune(now_ts)

    def observe_canonical_write(self, latency_ms: float, outcome: str) -> None:
        now_ts = monotonic()
        with self._lock:
            self._write_samples.append(
                WriteSample(ts=now_ts, latency_ms=latency_ms, outcome=outcome)
            )
            self._prune(now_ts)

    def observe_retrieval(self, mode: str, latency_ms: float) -> None:
        now_ts = monotonic()
        with self._lock:
            self._retrieval_samples.append(
                RetrievalSample(ts=now_ts, mode=mode, latency_ms=latency_ms)
            )
            self._prune(now_ts)

    def observe_graph_traversal(self, latency_ms: float) -> None:
        now_ts = monotonic()
        with self._lock:
            self._graph_traversal_samples.append(
                GraphTraversalSample(ts=now_ts, latency_ms=latency_ms)
            )
            self._prune(now_ts)

    def observe_graphrag_latencies(self, retrieval_latency_ms: float, total_latency_ms: float) -> None:
        now_ts = monotonic()
        with self._lock:
            self._graphrag_retrieval_samples.append(MetricSample(ts=now_ts, value=retrieval_latency_ms))
            self._graphrag_total_samples.append(MetricSample(ts=now_ts, value=total_latency_ms))
            self._prune(now_ts)

    def observe_llm_call(
        self,
        *,
        provider: str,
        model: str,
        success: bool,
        latency_ms: float,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> None:
        now_ts = monotonic()
        with self._lock:
            self._llm_samples.append(
                LLMCallSample(
                    ts=now_ts,
                    provider=provider,
                    model=model,
                    success=success,
                    latency_ms=latency_ms,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                )
            )
            self._prune(now_ts)

    def _window_request_samples(self, window_seconds: int) -> list[RequestSample]:
        now_ts = monotonic()
        cutoff = now_ts - window_seconds
        with self._lock:
            self._prune(now_ts)
            return [s for s in self._request_samples if s.ts >= cutoff]

    def _window_write_samples(self, window_seconds: int) -> list[WriteSample]:
        now_ts = monotonic()
        cutoff = now_ts - window_seconds
        with self._lock:
            self._prune(now_ts)
            return [s for s in self._write_samples if s.ts >= cutoff]

    def _window_retrieval_samples(self, window_seconds: int) -> list[RetrievalSample]:
        now_ts = monotonic()
        cutoff = now_ts - window_seconds
        with self._lock:
            self._prune(now_ts)
            return [s for s in self._retrieval_samples if s.ts >= cutoff]

    def _window_graph_traversal_samples(self, window_seconds: int) -> list[GraphTraversalSample]:
        now_ts = monotonic()
        cutoff = now_ts - window_seconds
        with self._lock:
            self._prune(now_ts)
            return [s for s in self._graph_traversal_samples if s.ts >= cutoff]

    def _window_metric_samples(self, samples: deque[MetricSample], window_seconds: int) -> list[MetricSample]:
        now_ts = monotonic()
        cutoff = now_ts - window_seconds
        with self._lock:
            self._prune(now_ts)
            return [s for s in samples if s.ts >= cutoff]

    def _window_llm_samples(self, window_seconds: int) -> list[LLMCallSample]:
        now_ts = monotonic()
        cutoff = now_ts - window_seconds
        with self._lock:
            self._prune(now_ts)
            return [s for s in self._llm_samples if s.ts >= cutoff]

    def runtime_snapshot(self, window_seconds: int = 300) -> dict[str, Any]:
        samples = self._window_request_samples(window_seconds)
        latencies = [s.latency_ms for s in samples]
        errors = [s for s in samples if s.status_code >= 500]
        with self._lock:
            inflight = self._inflight_requests
            peak = self._peak_inflight_requests

        return {
            "window_seconds": window_seconds,
            "request_count": len(samples),
            "requests_per_sec": (len(samples) / window_seconds) if window_seconds > 0 else None,
            "error_rate": (len(errors) / len(samples)) if samples else None,
            "latency_p50_ms": percentile(latencies, 50),
            "latency_p95_ms": percentile(latencies, 95),
            "concurrent_requests": inflight,
            "peak_concurrent_requests": peak,
        }

    def canonical_write_snapshot(self, window_seconds: int = 900) -> dict[str, Any]:
        samples = self._window_write_samples(window_seconds)
        latencies = [s.latency_ms for s in samples if s.outcome == "success"]

        failed = sum(1 for s in samples if s.outcome == "failed")
        rejected = sum(1 for s in samples if s.outcome == "rejected")
        duplicate = sum(1 for s in samples if s.outcome == "duplicate")
        success = sum(1 for s in samples if s.outcome == "success")

        return {
            "window_seconds": window_seconds,
            "samples": len(samples),
            "success_count": success,
            "failed_writes": failed,
            "rejected_writes": rejected,
            "duplicate_writes": duplicate,
            "write_p50_ms": percentile(latencies, 50),
            "write_p95_ms": percentile(latencies, 95),
        }

    def retrieval_snapshot(self, window_seconds: int = 900) -> dict[str, Any]:
        retrieval = self._window_retrieval_samples(window_seconds)
        graph = self._window_graph_traversal_samples(window_seconds)
        graphrag_retrieval = self._window_metric_samples(self._graphrag_retrieval_samples, window_seconds)
        graphrag_total = self._window_metric_samples(self._graphrag_total_samples, window_seconds)

        by_mode: dict[str, list[float]] = {}
        for sample in retrieval:
            by_mode.setdefault(sample.mode, []).append(sample.latency_ms)

        return {
            "window_seconds": window_seconds,
            "by_mode": {
                mode: {
                    "count": len(values),
                    "latency_p50_ms": percentile(values, 50),
                    "latency_p95_ms": percentile(values, 95),
                }
                for mode, values in by_mode.items()
            },
            "graph_query_count": len(graph),
            "graph_latency_p50_ms": percentile([s.latency_ms for s in graph], 50),
            "graph_latency_p95_ms": percentile([s.latency_ms for s in graph], 95),
            "graphrag_retrieval_p50_ms": percentile([s.value for s in graphrag_retrieval], 50),
            "graphrag_retrieval_p95_ms": percentile([s.value for s in graphrag_retrieval], 95),
            "graphrag_total_p50_ms": percentile([s.value for s in graphrag_total], 50),
            "graphrag_total_p95_ms": percentile([s.value for s in graphrag_total], 95),
        }

    def llm_snapshot(self, window_seconds: int = 900) -> dict[str, Any]:
        samples = self._window_llm_samples(window_seconds)
        successes = [s for s in samples if s.success]
        failures = [s for s in samples if not s.success]

        providers = sorted({s.provider for s in samples})
        models = sorted({s.model for s in samples})

        return {
            "window_seconds": window_seconds,
            "request_count": len(samples),
            "success_rate": (len(successes) / len(samples)) if samples else None,
            "failure_rate": (len(failures) / len(samples)) if samples else None,
            "latency_p50_ms": percentile([s.latency_ms for s in samples], 50),
            "latency_p95_ms": percentile([s.latency_ms for s in samples], 95),
            "prompt_tokens": sum(s.prompt_tokens for s in samples),
            "completion_tokens": sum(s.completion_tokens for s in samples),
            "providers": providers,
            "models": models,
        }


def percentile(values: list[float], p: int) -> float | None:
    if not values:
        return None
    if p <= 0:
        return min(values)
    if p >= 100:
        return max(values)

    ordered = sorted(values)
    idx = (len(ordered) - 1) * (p / 100.0)
    lower = int(idx)
    upper = min(lower + 1, len(ordered) - 1)
    weight = idx - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def metric_value(
    *,
    status: MetricStatus,
    value: Any = None,
    unit: str | None = None,
    detail: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"status": status.value, "value": value}
    if unit is not None:
        payload["unit"] = unit
    if detail is not None:
        payload["detail"] = detail
    return payload


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


metrics_collector = InProcessMetricsCollector()
