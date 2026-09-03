from __future__ import annotations

from typing import Any


STATUS_BADGE = {
    "AVAILABLE": "AVAILABLE",
    "NOT_INSTRUMENTED": "NOT_INSTRUMENTED",
    "NOT_CONNECTED": "NOT_CONNECTED",
    "DEGRADED": "DEGRADED",
}


def metric_status(metric: dict[str, Any]) -> str:
    return STATUS_BADGE.get(str(metric.get("status", "")), "UNKNOWN")


def metric_value_text(metric: dict[str, Any]) -> str:
    value = metric.get("value")
    unit = metric.get("unit")
    detail = metric.get("detail")

    if value is None:
        return str(detail or "Not instrumented")

    if isinstance(value, float):
        if unit == "ratio":
            return f"{value:.1%}"
        if unit in {"ms", "seconds"}:
            return f"{value:.2f} {unit}"
        if unit in {"req_per_sec", "events_per_sec"}:
            return f"{value:.3f}"
        return f"{value:.3f}"

    if unit:
        return f"{value} {unit}"
    return str(value)


def as_table_rows(group: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name, metric in group.items():
        rows.append(
            {
                "Metric": name,
                "Status": metric_status(metric),
                "Value": metric_value_text(metric),
            }
        )
    return rows
