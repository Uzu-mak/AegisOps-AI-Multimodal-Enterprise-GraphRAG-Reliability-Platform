"""
Create a draft question set from a proposal file (e.g. evals/proposals/maintnet_engines_v1.json).

The proposal names records by work-order number; this resolves them to the
active records in this database and saves a *draft* set whose questions are
marked with the proposal's labeling method (e.g. "assistant-proposed"). The
draft is not reviewed evidence: a person checks every label in the console,
submits it, and someone other than the author approves it.

    docker compose exec api python -m evals.propose_question_set evals/proposals/maintnet_engines_v1.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import select

from app.db.models.memory import MemoryRecord
from app.db.session import SessionLocal
from app.evaluation import datasets


def resolve(session, wo_numbers: list[str]) -> tuple[dict[str, str], dict[str, str], list[str]]:
    """Work-order number -> active record id (and title); numbers that don't resolve to exactly one record."""
    rows = session.execute(select(MemoryRecord.id, MemoryRecord.source_id, MemoryRecord.title)
                           .where(MemoryRecord.source_type == "work_order", MemoryRecord.status == "active",
                                  MemoryRecord.source_id.in_(wo_numbers))).all()
    found: dict[str, list] = {}
    for rid, sid, title in rows:
        found.setdefault(sid, []).append((str(rid), title))
    ids = {wo: hits[0][0] for wo, hits in found.items() if len(hits) == 1}
    titles = {hits[0][0]: hits[0][1] for hits in found.values() if len(hits) == 1}
    problems = [f"WO {wo}: {'not found' if wo not in found else f'{len(found[wo])} active records'}" for wo in wo_numbers if wo not in ids]
    return ids, titles, problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("proposal", type=Path)
    args = parser.parse_args(argv)
    proposal = json.loads(args.proposal.read_text(encoding="utf-8"))
    wanted = sorted({w for q in proposal["questions"] for w in q.get("wo", [])})
    with SessionLocal() as session:
        ids, titles, problems = resolve(session, wanted)
        if problems:
            print("Some work orders don't resolve to exactly one active record; nothing was saved:\n  " + "\n  ".join(problems), file=sys.stderr)
            return 1
        questions = [{
            "question": q["question"],
            "expected_memory_ids": [ids[w] for w in q.get("wo", [])],
            "expects_no_answer": bool(q.get("no_answer")),
            "labeling_method": proposal.get("labeling_method", "assistant-proposed"),
            "note": q.get("why"),
        } for q in proposal["questions"]]
        try:
            created = datasets.create_version(session, name=proposal["name"], questions=questions, author=proposal["author"],
                                              titles=titles, tenant_id=None)
        except datasets.QuestionSetError as exc:
            print(f"Not saved: {exc}", file=sys.stderr)
            return 1
    leaked = [q["question"] for q in created["questions"] if q["leaked"]]
    print(f"Saved {created['name']} v{created['version']} as a draft with {created['question_count']} questions "
          f"(content #{created['content_hash'][:8]}). Review it under Evaluation > Questions and labels.")
    if leaked:
        print("Flagged as repeating a record title: " + "; ".join(leaked))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
