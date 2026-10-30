"""Embedded text carries its context, so repair steps stay tied to their machine and incident."""
from __future__ import annotations

from types import SimpleNamespace

from app.services.semantic_service import SemanticIndexingService


def _mem(**kw):
    base = dict(memory_type="maintenance_action", title="WO 7: Oil cooler leaking", content="Removed and replaced oil cooler.",
                asset_id=None, component_id=None, incident_id=None, source_type="work_order", memory_metadata={})
    base.update(kw)
    return SimpleNamespace(**base)


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
