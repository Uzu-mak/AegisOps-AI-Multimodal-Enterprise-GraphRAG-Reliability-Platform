"""
AegisOps UI — Shared API client and utilities.
"""
from __future__ import annotations

import os
import requests
from typing import Any

API_URL = os.getenv("AEGISOPS_API_URL", "http://localhost:8000")


def api_get(path: str, params: dict | None = None) -> dict | list | None:
    try:
        resp = requests.get(f"{API_URL}{path}", params=params, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        return {"error": str(exc)}


def api_post(path: str, payload: dict) -> dict | None:
    try:
        resp = requests.post(
            f"{API_URL}{path}", json=payload, timeout=30
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        return {"error": str(exc)}


def status_badge(status: str) -> str:
    colours = {
        "active": "🟢",
        "archived": "🔵",
        "disputed": "🟡",
        "superseded": "⚫",
        "healthy": "🟢",
        "degraded": "🟡",
        "unhealthy": "🔴",
        "unavailable": "🔴",
    }
    return colours.get(status.lower(), "⬜") + " " + status
