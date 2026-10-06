from __future__ import annotations

import argparse
import csv
from pathlib import Path

from sqlalchemy import select

from app.db.models.memory import MemoryRecord
from app.db.session import SessionLocal


def export_candidates_csv(output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with SessionLocal() as session:
        rows = session.execute(
            select(MemoryRecord.id, MemoryRecord.memory_type, MemoryRecord.title, MemoryRecord.content)
            .order_by(MemoryRecord.created_at.desc())
        ).all()

    with output_path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(["memory_id", "memory_type", "text"])
        for memory_id, memory_type, title, content in rows:
            text = f"{title}\n{content}".strip()
            writer.writerow([str(memory_id), memory_type, text])

    return output_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export AegisOps memory candidates to CSV for human labeling.")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("evals/candidates.csv"),
        help="Destination CSV path.",
    )
    args = parser.parse_args(argv)

    output = export_candidates_csv(args.output)
    print(f"Exported {output}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
