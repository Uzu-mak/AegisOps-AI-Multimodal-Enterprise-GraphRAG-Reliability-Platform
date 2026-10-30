"""Embedded text carries its context, so repair steps stay tied to their machine and incident."""
from __future__ import annotations

from types import SimpleNamespace

from app.services.semantic_service import SemanticIndexingService


def _mem(**kw):
    base = dict(memory_type="maintenance_action", title="WO 7: Oil cooler leaking", content="Removed and replaced oil cooler.",
                asset_id=None, component_id=None, incident_id=None, source_type="work_order", memory_metadata={})
    base.update(kw)
    return SimpleNamespace(**base)


import pytest


@pytest.fixture(autouse=True)
def _header_format(monkeypatch):
    # These tests describe the context-header format; plain is the default.
    monkeypatch.setenv("SEMANTIC_TEXT_FORMAT", "context-header-1")


def text(m):
    return SemanticIndexingService(semantic_index=None, embedding_provider=None)._build_semantic_text(m)


def test_header_names_type_asset_component_and_incident():
    t = text(_mem(asset_id="ENG-2", component_id="R/H nacelle", incident_id="MN-100231"))
    assert t.startswith("Maintenance action on asset ENG-2, component R/H nacelle, incident MN-100231.")
    assert "Oil cooler leaking" in t and "Removed and replaced oil cooler." in t


def test_identical_steps_from_different_incidents_embed_differently():
    a, b = text(_mem(incident_id="MN-1")), text(_mem(incident_id="MN-2"))
    assert a != b


def test_weak_evidence_is_named_in_the_embedded_text():
    t = text(_mem(content="LEAK CK GOOD.", memory_metadata={"work_order": {"remedy": "LEAK CK GOOD."}}))
    assert "(routine check result)" in t


def test_records_with_no_text_still_index_nothing():
    assert text(_mem(title="", content="")) == ""


def test_plain_format_can_be_selected_for_a_before_and_after_measurement(monkeypatch):
    monkeypatch.setenv("SEMANTIC_TEXT_FORMAT", "plain")
    assert text(_mem(asset_id="ENG-2")) == "WO 7: Oil cooler leaking Removed and replaced oil cooler."


def test_vectors_record_the_format_that_built_them(monkeypatch):
    import uuid
    from datetime import datetime, timezone

    m = _mem(id=uuid.uuid4(), status="active", facility_id=None, created_at=datetime.now(timezone.utc), importance=0.5, confidence=0.8)
    svc = SemanticIndexingService(semantic_index=None, embedding_provider=None)
    assert svc._build_vector_record(m).to_dict()["text_format"] == "context-header-1"
    monkeypatch.setenv("SEMANTIC_TEXT_FORMAT", "plain")
    assert svc._build_vector_record(m).to_dict()["text_format"] == "plain"


def test_unknown_format_is_refused(monkeypatch):
    import pytest

    monkeypatch.setenv("SEMANTIC_TEXT_FORMAT", "fancy")
    with pytest.raises(ValueError):
        text(_mem())


def test_plain_is_the_default(monkeypatch):
    monkeypatch.delenv("SEMANTIC_TEXT_FORMAT", raising=False)
    assert text(_mem(asset_id="ENG-2")) == "WO 7: Oil cooler leaking Removed and replaced oil cooler."

