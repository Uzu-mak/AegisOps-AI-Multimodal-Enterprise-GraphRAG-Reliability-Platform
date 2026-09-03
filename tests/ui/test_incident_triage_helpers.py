from ui.incident_triage_helpers import format_confidence, normalize_incident_triage_result


def test_normalize_incident_triage_result_uses_flat_search_shape():
    view = normalize_incident_triage_result(
        {
            "memory_id": "mem-1",
            "retrieval_source": "semantic",
            "semantic_score": 0.91,
            "graph_path": None,
            "memory_type": "observation",
            "title": "Pump vibration spike",
            "content_preview": "Vibration exceeded threshold on pump P-102.",
            "status": "active",
            "asset_id": "pump-p102",
            "facility_id": "plant-west",
            "confidence": 0.82,
            "importance": 0.7,
        }
    )

    assert view["title"] == "Pump vibration spike"
    assert view["memory_type"] == "observation"
    assert view["context_label"] == "Asset: pump-p102"
    assert view["status"] == "active"
    assert view["content_preview"] == "Vibration exceeded threshold on pump P-102."
    assert format_confidence(view["confidence"]) == "82%"


def test_normalize_incident_triage_result_handles_missing_optional_fields():
    view = normalize_incident_triage_result({"title": None, "memory_type": None})

    assert view["title"] == "Untitled memory"
    assert view["memory_type"] == "unknown"
    assert view["context_label"] == ""
    assert view["content_preview"] == ""
    assert format_confidence(None) == "—"