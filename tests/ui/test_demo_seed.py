from ui.demo_seed import demo_seed_records, find_placeholder_records, plan_seed_records, seed_fingerprint


def test_plan_seed_records_is_idempotent():
    seed = demo_seed_records()
    pending_initial = plan_seed_records([])
    assert len(pending_initial) == len(seed)

    pending_after_seed = plan_seed_records(seed)
    assert pending_after_seed == []


def test_find_placeholder_records_reports_fields():
    records = [
        {
            "id": "record-1",
            "memory_type": "observation",
            "status": "active",
            "title": "string",
            "content": "string",
            "asset_id": "string",
            "facility_id": "string",
            "component_id": "string",
            "incident_id": "string",
            "source_type": "string",
        }
    ]

    placeholders = find_placeholder_records(records)
    assert len(placeholders) == 1
    assert placeholders[0]["id"] == "record-1"
    assert "title" in placeholders[0]["fields"]


def test_seed_fingerprint_stable_for_same_record():
    record = demo_seed_records()[0]
    assert seed_fingerprint(record) == seed_fingerprint(dict(record))
