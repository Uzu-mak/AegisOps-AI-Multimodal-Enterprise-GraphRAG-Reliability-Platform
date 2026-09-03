from ui.operations_catalog import (
    build_cascading_context_options,
    build_equipment_options,
    build_facility_options,
    build_incident_options,
    build_area_options,
    filter_records_by_context,
    format_memory_type,
    has_placeholder_defaults,
    placeholder_fields,
    humanize_identifier,
)


def test_humanize_identifier_formats_human_readable_labels():
    assert humanize_identifier("pump-p102") == "Pump P-102"
    assert humanize_identifier("facility_west") == "Facility West"


def test_format_memory_type_uses_operator_language():
    assert format_memory_type("diagnosis") == "Finding"
    assert format_memory_type("maintenance_action") == "Maintenance Action"


def test_equipment_and_facility_options_are_labelled_without_raw_ids():
    records = [
        {"asset_id": "pump-p102", "facility_id": "facility-west", "title": "Vibration spike"},
        {"asset_id": "pump-p103", "facility_id": "facility-west", "title": "Temperature rise"},
    ]

    equipment_labels = [option["label"] for option in build_equipment_options(records)]
    facility_labels = [option["label"] for option in build_facility_options(records)]

    assert any("Pump P-102" in label for label in equipment_labels)
    assert any("Pump P-103" in label for label in equipment_labels)
    assert all("(" not in label for label in equipment_labels)
    assert facility_labels == ["Facility West (2)"]


def test_selector_labels_never_show_schema_like_type_representations():
    records = [
        {
            "facility_id": "String(1)",
            "component_id": "String(1)",
            "asset_id": "String(1)",
            "incident_id": "String(1)",
            "memory_type": "incident",
            "title": "String(1)",
        }
    ]

    assert build_facility_options(records) == []
    assert build_area_options(records) == []
    assert build_equipment_options(records) == []
    assert build_incident_options(records) == []


def test_placeholder_detection_finds_swagger_defaults():
    record = {
        "title": "string",
        "content": "string",
        "asset_id": "string",
        "facility_id": "string",
        "component_id": "string",
        "incident_id": "string",
        "source_type": "string",
    }

    assert has_placeholder_defaults(record)
    assert set(placeholder_fields(record)) == {
        "title",
        "content",
        "asset_id",
        "facility_id",
        "component_id",
        "incident_id",
        "source_type",
    }


def test_incident_option_is_human_readable_and_preserves_internal_id():
    records = [
        {
            "facility_id": "facility-west",
            "component_id": "line-2",
            "asset_id": "robot-r17",
            "incident_id": "inc-2024-0042",
            "memory_type": "incident",
            "title": "Repeated Servo Fault - Robot R-17",
        }
    ]

    options = build_incident_options(records)
    assert options
    assert options[0]["label"] == "Repeated Servo Fault — Robot R-17"
    assert options[0]["value"] == "inc-2024-0042"


def test_incident_option_prefers_canonical_incident_title_over_other_types():
    records = [
        {
            "facility_id": "facility-west",
            "component_id": "line-2",
            "asset_id": "robot-r17",
            "incident_id": "inc-2026-0042",
            "memory_type": "resolution",
            "title": "Servo fault stabilized after harness repair",
        },
        {
            "facility_id": "facility-west",
            "component_id": "line-2",
            "asset_id": "robot-r17",
            "incident_id": "inc-2026-0042",
            "memory_type": "incident",
            "title": "Repeated Servo Fault - Robot R-17",
        },
    ]

    options = build_incident_options(records)
    assert options
    assert options[0]["value"] == "inc-2026-0042"
    assert options[0]["label"] == "Repeated Servo Fault — Robot R-17"


def test_cascading_options_preserve_context_relationships():
    records = [
        {
            "facility_id": "facility-west",
            "component_id": "line-2",
            "asset_id": "robot-r17",
            "incident_id": "inc-2024-0042",
            "memory_type": "incident",
            "title": "Repeated Servo Fault - Robot R-17",
        },
        {
            "facility_id": "facility-east",
            "component_id": "line-9",
            "asset_id": "robot-r88",
            "incident_id": "inc-2024-0099",
            "memory_type": "incident",
            "title": "Hydraulic Drift - Robot R-88",
        },
    ]

    context = build_cascading_context_options(records, facility_id="facility-west")
    area_values = {option["value"] for option in context["area"]}
    equipment_values = {option["value"] for option in context["equipment"]}
    incident_values = {option["value"] for option in context["incident"]}

    assert area_values == {"line-2"}
    assert equipment_values == {"robot-r17"}
    assert incident_values == {"inc-2024-0042"}


def test_filter_records_by_context_applies_all_keys():
    records = [
        {"facility_id": "facility-west", "component_id": "line-2", "asset_id": "robot-r17", "incident_id": "inc-1"},
        {"facility_id": "facility-west", "component_id": "line-3", "asset_id": "robot-r18", "incident_id": "inc-2"},
    ]

    filtered = filter_records_by_context(
        records,
        facility_id="facility-west",
        area_id="line-2",
        equipment_id="robot-r17",
        incident_id="inc-1",
    )
    assert len(filtered) == 1
    assert filtered[0]["asset_id"] == "robot-r17"
