from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from uuid import UUID

from app.db.models.memory import MemoryRecord
from app.db.session import SessionLocal
from sqlalchemy import select


REQUIRED_FIELDS = {"query_id", "query_text", "fault_family", "relevant_memory_ids", "notes"}
OPTIONAL_FIELDS = {"labeling_method", "source_documents", "source_memory_ids"}


def _load_existing_memory_ids() -> set[str]:
    with SessionLocal() as session:
        rows = session.execute(select(MemoryRecord.id)).scalars().all()
    return {str(memory_id) for memory_id in rows}


def validate_query_file(path: Path, known_memory_ids: set[str] | None = None) -> list[dict]:
    """Validate a JSONL query file and return the parsed objects."""
    if not path.exists():
        raise FileNotFoundError(f"Query file not found: {path}")

    known = known_memory_ids if known_memory_ids is not None else _load_existing_memory_ids()
    records: list[dict] = []
    seen_query_ids: set[str] = set()

    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            if not raw_line.strip():
                raise ValueError(f"Line {line_number}: blank lines are not allowed in the JSONL file.")
            try:
                record = json.loads(raw_line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Line {line_number}: invalid JSON: {exc.msg}") from exc

            if not isinstance(record, dict):
                raise ValueError(f"Line {line_number}: each row must be a JSON object.")

            unknown = set(record.keys()) - REQUIRED_FIELDS - OPTIONAL_FIELDS
            if unknown:
                raise ValueError(
                    f"Line {line_number}: unsupported keys: {sorted(unknown)}"
                )

            missing = REQUIRED_FIELDS - record.keys()
            if missing:
                raise ValueError(
                    f"Line {line_number}: missing required keys: {sorted(missing)}"
                )

            query_id = record["query_id"]
            query_text = record["query_text"]
            fault_family = record["fault_family"]
            relevant_memory_ids = record["relevant_memory_ids"]
            notes = record["notes"]

            if not isinstance(query_id, str) or not query_id.strip():
                raise ValueError(f"Line {line_number}: query_id must be a non-empty string.")
            if query_id in seen_query_ids:
                raise ValueError(f"Line {line_number}: duplicate query_id '{query_id}'.")
            seen_query_ids.add(query_id)

            if not isinstance(query_text, str) or not query_text.strip():
                raise ValueError(f"Line {line_number}: query_text must be a non-empty string.")
            if not isinstance(fault_family, str) or not fault_family.strip():
                raise ValueError(f"Line {line_number}: fault_family must be a non-empty string.")
            if not isinstance(notes, str):
                raise ValueError(f"Line {line_number}: notes must be a string.")
            if not isinstance(relevant_memory_ids, list):
                raise ValueError(f"Line {line_number}: relevant_memory_ids must be a list.")
            if not relevant_memory_ids:
                raise ValueError(f"Line {line_number}: relevant_memory_ids must not be empty for labeled queries.")
            if "labeling_method" not in record:
                record["labeling_method"] = "weakly_supervised_source_grounded"
            if "source_documents" not in record:
                record["source_documents"] = []

            normalized_ids: list[str] = []
            for memory_id in relevant_memory_ids:
                try:
                    uuid_value = str(UUID(str(memory_id)))
                except (TypeError, ValueError, AttributeError) as exc:
                    raise ValueError(
                        f"Line {line_number}: relevant_memory_id '{memory_id}' is not a valid UUID."
                    ) from exc
                if uuid_value not in known:
                    raise ValueError(
                        f"Line {line_number}: relevant_memory_id '{uuid_value}' does not exist in PostgreSQL."
                    )
                normalized_ids.append(uuid_value)

            record["relevant_memory_ids"] = normalized_ids
            records.append(record)

    return records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the AegisOps retrieval evaluation query file.")
    parser.add_argument("--file", type=Path, default=Path("evals/queries.jsonl"), help="Path to JSONL query file.")
    args = parser.parse_args(argv)

    try:
        validate_query_file(args.file)
    except Exception as exc:
        print(f"QUERY VALIDATION FAILED: {exc}", file=sys.stderr)
        return 1

    print(f"OK: {args.file} validated successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
