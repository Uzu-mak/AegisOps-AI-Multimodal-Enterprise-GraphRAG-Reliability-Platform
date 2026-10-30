"""
Work-order CSV import.

Turns a maintenance work-order export (IBM Maximo, SAP PM, or any CMMS that
can write CSV) into canonical AegisOps records, so a pilot runs on the plant's
own maintenance history instead of sample data.

Design rules
  * One work order becomes one ``maintenance_action`` record. Problem, cause
    and remedy text and codes are kept in the record text (so search and
    investigations can use them) and as structured fields in ``metadata``.
  * Columns are recognised by header name (Maximo and SAP PM spellings are
    built in); anything unrecognised is kept verbatim in ``metadata.extra``.
    A caller can override detection with an explicit ``column_map``.
  * ``source_type`` is ``work_order`` and ``source_id`` is the work-order
    number, so re-importing next week's export is idempotent: unchanged work
    orders are skipped and changed ones supersede the earlier version, which
    keeps its history.
  * ``incident_id`` is only set when the export names an originating ticket,
    notification or incident. AegisOps never invents incidents from work
    orders; records still connect through asset, location and facility.
  * Parsing is pure (no database); ``plan_import`` compares against existing
    records the caller supplies, so a dry run and the real run share one path.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.db.models.memory import MemoryType
from app.ingestion.quality import RULES_VERSION as QUALITY_RULES_VERSION, compute_flags
from app.services.memory_service import MemoryCreateData

SOURCE_TYPE = "work_order"
MAX_ROWS = 20_000
MAX_BYTES = 10 * 1024 * 1024
MAX_ISSUES_REPORTED = 200

# Canonical field -> header spellings (normalised: lower case, alphanumerics only).
FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "wo_number": ("wonum", "workorder", "workordernumber", "workorderid", "wonumber", "wo", "order", "ordernumber", "orderno", "aufnr"),
    "description": ("description", "shorttext", "ordershorttext", "title", "summary", "ktext"),
    "long_description": ("longdescription", "longdesc", "longtext", "details", "workperformed", "notes", "comments", "worklog"),
    "asset": ("assetnum", "asset", "assetid", "assetnumber", "equipment", "equipmentnumber", "equnr"),
    "location": ("location", "functionallocation", "funcloc", "tplnr", "workcenter", "line"),
    "facility": ("siteid", "site", "plant", "planningplant", "maintenanceplant", "facility", "facilityid", "werks"),
    "work_type": ("worktype", "ordertype", "wotype", "maintenanceactivitytype", "auart"),
    "status": ("status", "systemstatus", "userstatus", "wostatus"),
    "priority": ("wopriority", "priority", "prio"),
    "reported_at": ("reportdate", "reported", "reporteddate", "createdon", "created", "createddate", "notificationdate", "erdat"),
    "finished_at": ("actfinish", "actualfinish", "actualfinishdate", "completed", "completedon", "completiondate", "finishdate", "closedate", "teco"),
    "failure_class": ("failurecode", "failureclass", "catalogprofile"),
    "problem": ("problemcode", "problem", "damagecode", "damage", "symptom"),
    "cause": ("causecode", "cause", "causetext", "rootcause"),
    "remedy": ("remedycode", "remedy", "remedytext", "action", "activity", "correctiveaction"),
    "incident": ("origrecordid", "ticket", "ticketid", "servicerequest", "sr", "notification", "notificationnumber", "qmnum", "incident", "incidentid"),
}
FIELD_LABELS = {
    "wo_number": "Work order number",
    "description": "Description",
    "long_description": "Long description",
    "asset": "Asset",
    "location": "Location",
    "facility": "Site / plant",
    "work_type": "Work type",
    "status": "Status",
    "priority": "Priority",
    "reported_at": "Reported",
    "finished_at": "Actual finish",
    "failure_class": "Failure class",
    "problem": "Problem",
    "cause": "Cause",
    "remedy": "Remedy",
    "incident": "Originating ticket / incident",
}
REQUIRED_FIELDS = ("wo_number", "description")

CLOSED_STATUSES = {"comp", "close", "closed", "complete", "completed", "teco", "clsd", "done", "finished"}
EMERGENCY_TYPES = {"em", "emergency", "breakdown"}
CORRECTIVE_TYPES = {"cm", "corrective", "repair", "pm01", "em", "emergency", "breakdown"}
PREVENTIVE_TYPES = {"pm", "preventive", "pm02", "pm03", "planned", "inspection"}

_DATE_FORMATS_MONTH_FIRST = (
    "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M", "%m/%d/%Y %I:%M %p", "%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y",
    "%m/%d/%y %H:%M", "%m/%d/%y",
)
_DATE_FORMATS_DAY_FIRST = (
    "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y", "%d/%m/%y",
)
_DATE_FORMATS_UNAMBIGUOUS = (
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y/%m/%d %H:%M", "%Y/%m/%d",
    "%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y", "%Y%m%d", "%d-%b-%Y %H:%M", "%d-%b-%Y", "%d-%b-%y",
)


class WorkOrderImportError(ValueError):
    """The file as a whole cannot be imported (as opposed to a bad row)."""


@dataclass
class ImportOptions:
    is_synthetic: bool = False
    day_first: bool = False
    timezone: str = "UTC"
    source_system: str = "default"
    tenant_id: Optional[str] = None
    default_facility_id: Optional[str] = None
    column_map: dict[str, str] = field(default_factory=dict)
    file_name: Optional[str] = None


@dataclass
class RowIssue:
    row: int  # 1-based data row number; the header is row 0
    level: str  # "error" (row skipped) or "warning" (row imported)
    message: str

    def as_dict(self) -> dict[str, Any]:
        return {"row": self.row, "level": self.level, "message": self.message}


@dataclass
class ParsedWorkOrder:
    row: int
    wo_number: str
    data: MemoryCreateData
    fingerprint: str


@dataclass
class ParseResult:
    columns: list[str]
    mapping: dict[str, Optional[str]]  # canonical field -> CSV column (or None)
    unmapped_columns: list[str]
    rows_read: int
    work_orders: list[ParsedWorkOrder]
    issues: list[RowIssue]
    missing_required: list[str] = field(default_factory=list)  # canonical fields with no column

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.level == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.level == "warning")


@dataclass
class ExistingRecord:
    """The part of an existing active work-order record that planning needs."""
    memory_id: Any
    fingerprint: Optional[str]


@dataclass
class ImportPlan:
    create: list[ParsedWorkOrder]
    supersede: list[tuple[ExistingRecord, ParsedWorkOrder]]
    unchanged: list[ParsedWorkOrder]


# --------------------------------------------------------------------- helpers

def normalise_header(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def detect_mapping(columns: list[str], overrides: Optional[dict[str, str]] = None) -> dict[str, Optional[str]]:
    """Map canonical fields to CSV columns by header name; explicit overrides win."""
    overrides = overrides or {}
    unknown = set(overrides) - set(FIELD_ALIASES)
    if unknown:
        raise WorkOrderImportError(f"Unknown field(s) in column_map: {', '.join(sorted(unknown))}")
    missing = [c for c in overrides.values() if c and c not in columns]
    if missing:
        raise WorkOrderImportError(f"column_map names column(s) not in the file: {', '.join(missing)}")

    by_norm: dict[str, str] = {}
    for col in columns:
        by_norm.setdefault(normalise_header(col), col)

    mapping: dict[str, Optional[str]] = {}
    used: set[str] = set(c for c in overrides.values() if c)
    for fld, aliases in FIELD_ALIASES.items():
        if fld in overrides:
            mapping[fld] = overrides[fld] or None
            continue
        mapping[fld] = None
        for alias in aliases:
            col = by_norm.get(alias)
            if col is not None and col not in used:
                mapping[fld] = col
                used.add(col)
                break
    return mapping


def parse_datetime(value: str, *, day_first: bool, tz: ZoneInfo) -> Optional[datetime]:
    text = (value or "").strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        dt = None
        ambiguous = _DATE_FORMATS_DAY_FIRST if day_first else _DATE_FORMATS_MONTH_FIRST
        for fmt in _DATE_FORMATS_UNAMBIGUOUS + ambiguous:
            try:
                dt = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        if dt is None:
            raise ValueError(f"unrecognised date '{text}'")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return dt.astimezone(timezone.utc)


def _priority_importance(priority: str, work_type: str) -> float:
    base = 0.5
    p = (priority or "").strip()
    if p:
        m = re.match(r"\d+", p)
        if m:
            base = {1: 0.9, 2: 0.75, 3: 0.6, 4: 0.45, 5: 0.4}.get(int(m.group()), 0.4)
        else:
            base = {"urgent": 0.9, "emergency": 0.9, "high": 0.75, "medium": 0.6, "normal": 0.6, "low": 0.45}.get(p.lower(), 0.5)
    if work_type.lower() in EMERGENCY_TYPES:
        base = min(1.0, base + 0.1)
    return round(base, 2)


def _confidence(status: str, cause: str, remedy: str) -> float:
    # How far the record can be relied on as a statement of what happened:
    # a closed work order with recorded cause and remedy is the strongest.
    c = 0.6
    if status.lower() in CLOSED_STATUSES:
        c += 0.2
    if cause and remedy:
        c += 0.1
    return round(min(c, 0.95), 2)


def work_type_class(work_type: str) -> str:
    wt = (work_type or "").strip().lower()
    if wt in EMERGENCY_TYPES:
        return "emergency"
    if wt in CORRECTIVE_TYPES:
        return "corrective"
    if wt in PREVENTIVE_TYPES:
        return "preventive"
    return "other" if wt else "unknown"


def fingerprint(data: MemoryCreateData) -> str:
    payload = {
        "title": data.title, "content": data.content, "asset_id": data.asset_id,
        "component_id": data.component_id, "facility_id": data.facility_id,
        "incident_id": data.incident_id, "observed_at": data.observed_at.isoformat() if data.observed_at else None,
        "fields": data.memory_metadata.get("work_order"),
        "extra": data.memory_metadata.get("extra", {}),
        "is_synthetic": data.is_synthetic,
        "tenant_id": data.tenant_id,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:32]


# ----------------------------------------------------------------------- parse

def parse_work_orders(csv_text: str, options: Optional[ImportOptions] = None) -> ParseResult:
    options = options or ImportOptions()
    if len(csv_text.encode("utf-8", errors="ignore")) > MAX_BYTES:
        raise WorkOrderImportError(f"File is larger than {MAX_BYTES // (1024 * 1024)} MB; split the export.")
    text = csv_text.lstrip("﻿")
    if not text.strip():
        raise WorkOrderImportError("The file is empty.")
    try:
        tz = ZoneInfo(options.timezone or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        raise WorkOrderImportError(f"Unknown time zone '{options.timezone}'.")

    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    columns = [c for c in (reader.fieldnames or []) if c is not None]
    if not columns:
        raise WorkOrderImportError("No header row found.")

    mapping = detect_mapping(columns, options.column_map)
    mapped_cols = {c for c in mapping.values() if c}
    unmapped = [c for c in columns if c not in mapped_cols]
    missing = [f for f in REQUIRED_FIELDS if not mapping.get(f)]
    if missing:
        # Not an exception: the caller shows the columns so a person can pick them.
        return ParseResult(columns=columns, mapping=mapping, unmapped_columns=unmapped, rows_read=0,
                           work_orders=[], issues=[], missing_required=missing)

    issues: list[RowIssue] = []
    out: list[ParsedWorkOrder] = []
    seen: dict[str, int] = {}
    rows_read = 0

    for idx, raw in enumerate(reader, start=1):
        rows_read = idx
        if idx > MAX_ROWS:
            raise WorkOrderImportError(f"More than {MAX_ROWS:,} rows; split the export.")
        get = lambda f: (raw.get(mapping[f]) or "").strip() if mapping.get(f) else ""  # noqa: E731
        if not any((v or "").strip() for k, v in raw.items() if k is not None):
            continue  # blank line

        wo = get("wo_number")
        desc = get("description")
        if not wo:
            issues.append(RowIssue(idx, "error", "No work order number; row skipped."))
            continue
        if not desc:
            issues.append(RowIssue(idx, "error", f"Work order {wo} has no description; row skipped."))
            continue
        facility = get("facility") or options.default_facility_id
        key = f"{facility or ''}|{wo}"
        if key in seen:
            issues.append(RowIssue(idx, "warning", f"Work order {wo} also appears on row {seen[key]}; kept the first and skipped this row."))
            continue
        seen[key] = idx

        finished_at = None
        reported_at = None
        for fld in ("finished_at", "reported_at"):
            try:
                val = parse_datetime(get(fld), day_first=options.day_first, tz=tz)
            except ValueError as exc:
                issues.append(RowIssue(idx, "warning", f"Work order {wo}: {FIELD_LABELS[fld].lower()} {exc}; left blank."))
                val = None
            if fld == "reported_at":
                reported_at = val
            else:
                finished_at = val
        observed_at = finished_at or reported_at
        if observed_at is None:
            issues.append(RowIssue(idx, "warning", f"Work order {wo} has no usable date; it will sort by import time."))

        work_type = get("work_type")
        status = get("status")
        priority = get("priority")
        problem, cause, remedy = get("problem"), get("cause"), get("remedy")
        failure_class = get("failure_class")
        long_desc = get("long_description")
        asset = get("asset") or None
        location = get("location") or None
        incident = get("incident") or None

        # The title already carries the short description; lead the text with
        # the long description when there is one so it is not said twice.
        lead = long_desc if long_desc and long_desc != desc else desc
        lines = [lead if lead.endswith((".", "!", "?")) else f"{lead}."]
        codes = [f"{label}: {v}" for label, v in (("Failure class", failure_class), ("Problem", problem), ("Cause", cause), ("Remedy", remedy)) if v]
        if codes:
            lines.append(". ".join(codes) + ".")
        facts = [f"{label} {v}" for label, v in (("Work type", work_type), ("status", status), ("priority", priority)) if v]
        if facts:
            lines.append(", ".join(facts) + ".")
        if not asset:
            issues.append(RowIssue(idx, "warning", f"Work order {wo} has no asset; it will only link by location and site."))

        extra = {c: raw[c] for c in unmapped if raw.get(c) not in (None, "")}
        wo_fields = {
            "number": wo, "work_type": work_type or None, "work_type_class": work_type_class(work_type),
            "status": status or None, "priority": priority or None, "failure_class": failure_class or None,
            "problem": problem or None, "cause": cause or None, "remedy": remedy or None,
            "reported_at": reported_at.isoformat() if reported_at else None,
            "finished_at": finished_at.isoformat() if finished_at else None,
            "location": location,
        }
        title = f"WO {wo}: {desc}"
        data = MemoryCreateData(
            memory_type=MemoryType.MAINTENANCE_ACTION.value,
            title=title if len(title) <= 160 else title[:157] + "...",
            content="\n".join(lines),
            source_type=SOURCE_TYPE,
            tenant_id=options.tenant_id,
            source_id=wo,
            asset_id=asset,
            component_id=location,
            facility_id=facility,
            incident_id=incident,
            observed_at=observed_at,
            confidence=_confidence(status, cause, remedy),
            importance=_priority_importance(priority, work_type),
            is_synthetic=options.is_synthetic,
            memory_metadata={"work_order": wo_fields, **({"extra": extra} if extra else {})},
        )
        fp = fingerprint(data)
        data.memory_metadata["import"] = {"fingerprint": fp, "source_system": options.source_system, "file_name": options.file_name, "row": idx}
        # Quality flags sit outside the fingerprint: re-importing the same file stays a no-op.
        data.memory_metadata["quality"] = {"flags": compute_flags(content=data.content, asset_id=asset, source_type=SOURCE_TYPE, meta=data.memory_metadata),
                                           "rules": QUALITY_RULES_VERSION}
        out.append(ParsedWorkOrder(row=idx, wo_number=wo, data=data, fingerprint=fp))

    if rows_read == 0:
        raise WorkOrderImportError("The file has a header row but no work orders.")
    return ParseResult(columns=columns, mapping=mapping, unmapped_columns=unmapped,
                       rows_read=rows_read, work_orders=out, issues=issues)


def existing_key(facility_id: Optional[str], source_id: str) -> str:
    return f"{facility_id or ''}|{source_id}"


def plan_import(parsed: Iterable[ParsedWorkOrder], existing: dict[str, ExistingRecord]) -> ImportPlan:
    """Split parsed work orders into new, changed (supersede) and unchanged."""
    plan = ImportPlan(create=[], supersede=[], unchanged=[])
    for wo in parsed:
        prior = existing.get(existing_key(wo.data.facility_id, wo.wo_number))
        if prior is None:
            plan.create.append(wo)
        elif prior.fingerprint == wo.fingerprint:
            plan.unchanged.append(wo)
        else:
            plan.supersede.append((prior, wo))
    return plan


def preview_record(wo: ParsedWorkOrder) -> dict[str, Any]:
    d = wo.data
    return {
        "row": wo.row, "title": d.title, "content": d.content, "asset_id": d.asset_id,
        "component_id": d.component_id, "facility_id": d.facility_id, "incident_id": d.incident_id,
        "observed_at": d.observed_at.isoformat() if d.observed_at else None,
        "finished_at": d.memory_metadata["work_order"]["finished_at"],
        "reported_at": d.memory_metadata["work_order"]["reported_at"],
        "confidence": d.confidence, "importance": d.importance,
        "work_type_class": d.memory_metadata["work_order"]["work_type_class"],
    }


# ------------------------------------------------------------------ run import

def run_import(service: Any, csv_text: str, options: Optional[ImportOptions] = None, *, dry_run: bool = True) -> dict[str, Any]:
    """
    Parse, plan against what is already stored, and (unless dry_run) write.

    ``service`` is a RealMemoryService (needs active_source_fingerprints and
    bulk_import). Returns a JSON-ready report used by the API, console and CLI.
    """
    options = options or ImportOptions()
    parsed = parse_work_orders(csv_text, options)
    if parsed.missing_required and not dry_run:
        raise WorkOrderImportError(
            "Could not find a column for: " + ", ".join(FIELD_LABELS[f] for f in parsed.missing_required)
            + f". Columns in the file: {', '.join(parsed.columns)}. Map them and preview again.")
    found = service.active_source_fingerprints(
        source_type=SOURCE_TYPE, source_ids=sorted({w.wo_number for w in parsed.work_orders}),
        source_system=options.source_system, tenant_id=options.tenant_id)
    existing = {k: ExistingRecord(memory_id=mid, fingerprint=fp) for k, (mid, fp) in found.items()}
    plan = plan_import(parsed.work_orders, existing)

    written = {"created": 0, "superseded": 0}
    if not dry_run and (plan.create or plan.supersede):
        written = service.bulk_import(
            creates=[w.data for w in plan.create],
            supersedes=[(prior.memory_id, w.data) for prior, w in plan.supersede],
        )

    assets = sorted({w.data.asset_id for w in parsed.work_orders if w.data.asset_id})
    facilities = sorted({w.data.facility_id for w in parsed.work_orders if w.data.facility_id})
    dates = sorted(w.data.observed_at for w in parsed.work_orders if w.data.observed_at)
    quality: dict[str, int] = {}
    for w in parsed.work_orders:
        for f in w.data.memory_metadata.get("quality", {}).get("flags", []):
            quality[f] = quality.get(f, 0) + 1
    by_class: dict[str, int] = {}
    for w in parsed.work_orders:
        c = w.data.memory_metadata["work_order"]["work_type_class"]
        by_class[c] = by_class.get(c, 0) + 1

    return {
        "dry_run": dry_run,
        "file_name": options.file_name,
        "is_synthetic": options.is_synthetic,
        "missing_required": [{"field": f, "label": FIELD_LABELS[f]} for f in parsed.missing_required],
        "rows_read": parsed.rows_read,
        "valid_work_orders": len(parsed.work_orders),
        "new": len(plan.create),
        "changed": len(plan.supersede),
        "unchanged": len(plan.unchanged),
        "errors": parsed.error_count,
        "warnings": parsed.warning_count,
        "written": written,
        "queued_for_projection": 0 if dry_run else written["created"] + written["superseded"],
        "columns": parsed.columns,
        "mapping": [{"field": f, "label": FIELD_LABELS[f], "column": parsed.mapping.get(f), "required": f in REQUIRED_FIELDS}
                    for f in FIELD_ALIASES],
        "unmapped_columns": parsed.unmapped_columns,
        "assets": len(assets),
        "facilities": facilities,
        "date_range": [dates[0].isoformat(), dates[-1].isoformat()] if dates else None,
        "work_type_classes": by_class,
        "quality_flags": quality,
        "issues": [i.as_dict() for i in parsed.issues[:MAX_ISSUES_REPORTED]],
        "issues_truncated": max(0, len(parsed.issues) - MAX_ISSUES_REPORTED),
        "sample": [preview_record(w) for w in (plan.create + [w for _, w in plan.supersede])[:5]],
    }


def _main(argv: Optional[list[str]] = None) -> int:
    import argparse
    from pathlib import Path

    from app.db.session import SessionLocal
    from app.repositories.memory_repository import SQLAlchemyMemoryRepository
    from app.services.memory_service import RealMemoryService

    ap = argparse.ArgumentParser(description="Import a CMMS work-order CSV export into AegisOps.")
    ap.add_argument("csv_file", type=Path)
    ap.add_argument("--source-system", default="default", help="Stable CMMS instance identity")
    ap.add_argument("--tenant-id", default=None)
    ap.add_argument("--apply", action="store_true", help="Write the records (default is a dry run that only reports).")
    ap.add_argument("--synthetic", action="store_true", help="Flag every imported record as synthetic / sample data.")
    ap.add_argument("--day-first", action="store_true", help="Read ambiguous dates as DD/MM/YYYY instead of MM/DD/YYYY.")
    ap.add_argument("--timezone", default="UTC", help="Time zone of dates without an offset (e.g. America/Los_Angeles).")
    ap.add_argument("--facility", help="Facility id for rows with no site/plant column.")
    ap.add_argument("--map", action="append", default=[], metavar="FIELD=COLUMN",
                    help=f"Override column detection; fields: {', '.join(FIELD_ALIASES)}")
    args = ap.parse_args(argv)

    column_map = {}
    for item in args.map:
        if "=" not in item:
            ap.error(f"--map expects FIELD=COLUMN, got '{item}'")
        k, v = item.split("=", 1)
        column_map[k.strip()] = v.strip()
    options = ImportOptions(source_system=args.source_system, tenant_id=args.tenant_id, is_synthetic=args.synthetic, day_first=args.day_first, timezone=args.timezone,
                            default_facility_id=args.facility, column_map=column_map, file_name=args.csv_file.name)
    service = RealMemoryService(repository=SQLAlchemyMemoryRepository(), session_factory=SessionLocal)
    try:
        report = run_import(service, args.csv_file.read_text(encoding="utf-8-sig"), options, dry_run=not args.apply)
    except WorkOrderImportError as exc:
        print(f"error: {exc}")
        return 2
    if report["missing_required"]:
        print("error: no column found for " + ", ".join(m["label"] for m in report["missing_required"])
              + f". Columns in the file: {', '.join(report['columns'])}. Name them with --map FIELD=COLUMN.")
        return 2
    print(json.dumps({k: v for k, v in report.items() if k not in ("sample", "columns")}, indent=2, default=str))
    if report["dry_run"]:
        print("\nDry run only. Re-run with --apply to write these records.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
