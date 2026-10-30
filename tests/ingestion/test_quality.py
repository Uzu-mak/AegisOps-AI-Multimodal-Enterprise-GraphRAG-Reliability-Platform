"""Write-side quality flags: set at import, outside the fingerprint, derived on read for older records."""
from __future__ import annotations

from types import SimpleNamespace

from app.ingestion.quality import compute_flags, quality_flags
from app.ingestion.work_orders import ImportOptions, fingerprint, parse_work_orders

CSV = (
    "WONUM,DESCRIPTION,REMEDY,SOURCE_TRUNCATED\n"
    "1,ENGINE RAN ROUGH AFTER START.,REMOVED & REPLACED ENGINE DRIVEN FUEL PUMP,\n"
    "2,ENGINE RAN ROUGH AFTER START.,\"RAN A/C, OPS & LEAK CK GOOD.\",\n"
    "3,OIL COOLER REQUIRES TIME CHANGE.,FOR BILLING PURPOSES ONLY,\n"
    "4,#3 CYL OIL RETURN LINE CHAFING ON WIRE BUNDLE.,REMOVED & REPLACED OIL RETURN LINE AND CLAMPED CL,action\n"
)


def _flags(remedy, **extra):
    return compute_flags(content="", asset_id="A1", source_type="work_order", meta={"work_order": {"remedy": remedy}, "extra": extra})


def test_rules_separate_real_repairs_from_check_results_and_paperwork():
    assert _flags("REMOVED & REPLACED FUEL SERVO") == []
    assert _flags("REPLACED GASKET, LEAK CK GOOD.") == []  # a repair that was then checked is still a repair
    assert _flags("LEAK CK GOOD.") == ["routine_check"]
    assert _flags("RAN A/C, ALL CHECKS GOOD.") == ["routine_check"]
    assert _flags("FOR BILLING PURPOSES ONLY") == ["administrative"]
    assert _flags("C/W, NO DEFECTS NOTED. NO FURTHER ACTION REQUIRED") == []  # an inspection result, not paperwork
    assert "truncated" in _flags("REMOVED CYL", SOURCE_TRUNCATED="action")


def test_import_stores_flags_and_counts_them_without_changing_the_fingerprint():
    parsed = parse_work_orders(CSV, ImportOptions(timezone="UTC", source_system="MaintNet"))
    flags = {w.wo_number: w.data.memory_metadata["quality"]["flags"] for w in parsed.work_orders}
    assert flags["1"] == ["no_asset"]
    assert "routine_check" in flags["2"] and "administrative" in flags["3"] and "truncated" in flags["4"]
    w = parsed.work_orders[0]
    before = w.fingerprint
    assert fingerprint(w.data) == before  # quality is added after fingerprinting and ignored by it


def test_older_records_get_flags_on_read_and_stored_flags_win():
    old = SimpleNamespace(content="x", asset_id=None, source_type="work_order",
                          memory_metadata={"work_order": {"remedy": "FOR BILLING PURPOSES ONLY"}})
    assert quality_flags(old) == ["administrative", "no_asset"]
    old.memory_metadata["quality"] = {"flags": []}
    assert quality_flags(old) == []
