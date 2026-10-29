"""Convert the MaintNet aircraft maintenance logs into an AegisOps work-order CSV.

Source: "Aircraft Historical Maintenance Dataset (2012-2017)" on Kaggle, derived
from MaintNet (Akhbardeh, Desell and Zampieri, 2020, arXiv:2005.12443), courtesy
of the University of North Dakota Aviation Program. Licence: Open Database
Licence (database) and Database Contents Licence (contents); keep this
attribution with anything built from it. It is a public training-fleet dataset,
not any customer's maintenance history.

Input  (Aircraft_Annotation_DataFile.csv): IDENT, PROBLEM, ACTION
Output (importer-ready):                    WONUM, DESCRIPTION, REMEDY, INCIDENT,
                                            SOURCE_TRUNCATED

Choices, each made so AegisOps doesn't invent structure the data lacks:
- One row stays one work order (WONUM = IDENT, DESCRIPTION = PROBLEM,
  REMEDY = ACTION).
- INCIDENT groups consecutive rows that repeat the same problem text: the log
  records several actions against one reported problem that way (for example
  IDENT 100001-100003). This is the only grouping the data itself supports.
- The source cuts PROBLEM at 60 and ACTION at 55 characters (about 7% and
  15% of rows end mid-word). Text is kept exactly as published; the
  SOURCE_TRUNCATED column (kept on each record as an extra field) says which
  field was cut, so nobody mistakes a clipped entry for a complete one.
- No site, asset or date columns: the data is de-identified and undated. Leave
  "Default facility" empty when importing, so 6,000+ records are not linked to
  each other through one shared site.

Usage:
    python scripts/prepare_maintnet.py Aircraft_Annotation_DataFile.csv [out.csv]
"""
from __future__ import annotations

import csv
import sys
from collections import Counter
from pathlib import Path
from typing import Iterable, Iterator


# Field widths in the published file. Text that fills the field and doesn't end
# a sentence was cut by the source; a full-width sentence ending in "." is kept
# as complete.
PROBLEM_LIMIT, ACTION_LIMIT = 60, 55


def _norm(text: str) -> str:
    return " ".join((text or "").split()).upper().rstrip(".")


def convert(rows: Iterable[dict]) -> Iterator[dict]:
    """Yield importer rows; consecutive repeats of a problem share an incident."""
    incident = None
    previous = None
    for row in rows:
        ident = (row.get("IDENT") or "").strip()
        problem = " ".join((row.get("PROBLEM") or "").split())
        action = " ".join((row.get("ACTION") or "").split())
        if not ident or not problem:
            continue
        key = _norm(problem)
        if key != previous:
            incident = f"MN-{ident}"
            previous = key
        cut = [name for name, raw, limit in (("problem", row.get("PROBLEM") or "", PROBLEM_LIMIT), ("action", row.get("ACTION") or "", ACTION_LIMIT))
               if len(raw) >= limit and not raw.rstrip().endswith((".", ")"))]
        yield {"WONUM": ident, "DESCRIPTION": problem, "REMEDY": action, "INCIDENT": incident, "SOURCE_TRUNCATED": "+".join(cut)}


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    src = Path(argv[0])
    out = Path(argv[1]) if len(argv) > 1 else src.with_name("maintnet_workorders.csv")
    with src.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        missing = {"IDENT", "PROBLEM", "ACTION"} - set(reader.fieldnames or [])
        if missing:
            print(f"{src} is missing columns: {', '.join(sorted(missing))}", file=sys.stderr)
            return 1
        rows = list(convert(reader))
    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["WONUM", "DESCRIPTION", "REMEDY", "INCIDENT", "SOURCE_TRUNCATED"])
        writer.writeheader()
        writer.writerows(rows)
    sizes = Counter(r["INCIDENT"] for r in rows)
    incidents, multi = len(sizes), sum(1 for n in sizes.values() if n > 1)
    cut = sum(1 for r in rows if r["SOURCE_TRUNCATED"])
    print(f"Wrote {len(rows)} work orders in {incidents} incidents ({multi} with more than one action) to {out}; {cut} rows have text cut off in the source")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
