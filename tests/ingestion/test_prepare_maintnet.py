"""The MaintNet converter groups only what the data itself groups."""
import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location("prepare_maintnet", Path(__file__).resolve().parents[2] / "scripts" / "prepare_maintnet.py")
prepare = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(prepare)


def test_consecutive_repeats_of_a_problem_share_an_incident():
    rows = [
        {"IDENT": "100001", "PROBLEM": "ENGINE IDLE OVERRIDE KILLED ENGINE.", "ACTION": "TRIED TO ADJUST IDLE."},
        {"IDENT": "100002", "PROBLEM": "ENGINE IDLE OVERRIDE KILLED ENGINE.", "ACTION": "REMOVED & REPLACED FUEL SERVO"},
        {"IDENT": "100003", "PROBLEM": "#2 INTAKE IS LEAKING.", "ACTION": "REPLACED GASKET."},
        {"IDENT": "100004", "PROBLEM": "ENGINE IDLE OVERRIDE KILLED ENGINE.", "ACTION": "RAN UP, OK."},
    ]
    out = list(prepare.convert(rows))
    assert [r["INCIDENT"] for r in out] == ["MN-100001", "MN-100001", "MN-100003", "MN-100004"]
    assert out[1] == {"WONUM": "100002", "DESCRIPTION": "ENGINE IDLE OVERRIDE KILLED ENGINE.", "REMEDY": "REMOVED & REPLACED FUEL SERVO", "INCIDENT": "MN-100001", "SOURCE_TRUNCATED": ""}


def test_text_cut_by_the_source_is_marked_not_altered():
    row = {"IDENT": "100004", "PROBLEM": "HAD ENGINE CHOKE & BRIEFLY LOSE POWER ON DEPARTURE. FULL THR", "ACTION": "PERFORMED ENGINE RUN UP, FOUND CYL 2 LOWER PLUG FOULED."}
    (out,) = prepare.convert([row])
    assert out["DESCRIPTION"] == row["PROBLEM"] and out["REMEDY"] == row["ACTION"]
    # The problem stops mid-word; the action fills the field but ends a sentence.
    assert out["SOURCE_TRUNCATED"] == "problem"


def test_rows_without_an_id_or_problem_are_dropped():
    rows = [{"IDENT": "", "PROBLEM": "X", "ACTION": "Y"}, {"IDENT": "1", "PROBLEM": "  ", "ACTION": "Y"}]
    assert list(prepare.convert(rows)) == []
