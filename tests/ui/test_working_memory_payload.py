from ui.working_memory_payload import build_promotion_payload


def test_build_promotion_payload_uses_public_metadata_field():
    payload = build_promotion_payload(
        memory_type="observation",
        title="Promoted item",
        content="Working memory content",
        source_type="operator",
        asset_id="asset-1",
        confidence=0.8,
        importance=0.6,
    )

    assert "metadata" in payload
    assert "memory_metadata" not in payload
    assert payload["metadata"] == {"promoted_from": "working_memory"}
