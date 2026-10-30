"""Evaluation run history: every console run is kept, so runs can be listed,
reopened and compared. Only evaluation tables are written here; canonical
memories are never touched.

Column types are generic (JSON, Uuid) with a JSONB variant on PostgreSQL, so
the SQLite test fixtures that build the whole schema keep working.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, Uuid, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.db.base import Base

_JSON = JSON().with_variant(JSONB(), "postgresql")


class EvalRunRecord(Base):
    __tablename__ = "eval_run"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=lambda: datetime.now(timezone.utc))
    tenant_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="console")
    trigger: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    k: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(200), nullable=False)
    llm_model: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    commit: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    question_count: Mapped[int] = mapped_column(Integer, nullable=False)
    modes_run: Mapped[list] = mapped_column(_JSON, nullable=False)
    unavailable_modes: Mapped[dict] = mapped_column(_JSON, nullable=False, default=dict)
    per_mode: Mapped[dict] = mapped_column(_JSON, nullable=False)
    failure_taxonomy: Mapped[dict] = mapped_column(_JSON, nullable=False, default=dict)


class EvalCaseResultRecord(Base):
    __tablename__ = "eval_case_result"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("eval_run.id", ondelete="CASCADE"), nullable=False, index=True)
    case_id: Mapped[str] = mapped_column(String(100), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    mode: Mapped[str] = mapped_column(String(20), nullable=False)
    expected_memory_ids: Mapped[list] = mapped_column(_JSON, nullable=False, default=list)
    anchor_memory_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    labeled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    retrieved_memory_ids: Mapped[list] = mapped_column(_JSON, nullable=False, default=list)
    recall_at_5: Mapped[float] = mapped_column(Float, nullable=False)
    recall_at_k: Mapped[float] = mapped_column(Float, nullable=False)
    mrr: Mapped[float] = mapped_column(Float, nullable=False)
    groundedness: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    citation_accuracy: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    latency_ms: Mapped[float] = mapped_column(Float, nullable=False)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


CASE_FIELDS = ("case_id", "question", "mode", "labeled", "recall_at_5", "recall_at_k", "mrr",
               "groundedness", "citation_accuracy", "retrieved_memory_ids", "latency_ms", "error")


def save_run(session: Session, payload: dict[str, Any], *, expected: dict[str, list[str]], anchors: dict[str, Optional[str]],
             tenant_id: Optional[str], llm_model: Optional[str], commit: Optional[str]) -> UUID:
    """Persist a run in the response shape produced by POST /evaluation/runs."""
    questions = {c["question"] for c in payload["cases"]}
    run = EvalRunRecord(
        id=UUID(payload["run_id"]), created_at=datetime.fromisoformat(payload["generated_at"]), tenant_id=tenant_id,
        k=payload["k"], embedding_model=payload["embedding_model"], llm_model=llm_model, commit=commit,
        question_count=len(questions), modes_run=payload["modes_run"], unavailable_modes=payload["unavailable_modes"],
        per_mode=payload["per_mode"], failure_taxonomy=payload["failure_taxonomy"],
    )
    session.add(run)
    session.flush()
    for c in payload["cases"]:
        session.add(EvalCaseResultRecord(
            run_id=run.id, expected_memory_ids=expected.get(c["case_id"], []), anchor_memory_id=anchors.get(c["case_id"]),
            **{f: c[f] for f in CASE_FIELDS},
        ))
    session.commit()
    return run.id


def _scope(stmt, tenant_id: Optional[str]):
    return stmt.where(EvalRunRecord.tenant_id == tenant_id) if tenant_id is not None else stmt


def list_runs(session: Session, *, tenant_id: Optional[str], limit: int = 50) -> list[dict[str, Any]]:
    rows = list(session.execute(_scope(select(EvalRunRecord), tenant_id).order_by(EvalRunRecord.created_at.desc()).limit(limit)).scalars())
    out = [_summary(r) for r in rows]
    _attach_question_sets(session, out, tenant_id)
    return out


def _attach_question_sets(session: Session, runs: list[dict[str, Any]], tenant_id: Optional[str]) -> None:
    """Say which versioned question set each run measured, by content hash (None for ad hoc questions)."""
    from app.evaluation.datasets import run_dataset_hash, sets_by_hash

    if not runs:
        return
    ids = [UUID(r["run_id"]) for r in runs]
    cases: dict[str, list[dict[str, Any]]] = {}
    for run_id, question, expected, anchor in session.execute(
            select(EvalCaseResultRecord.run_id, EvalCaseResultRecord.question, EvalCaseResultRecord.expected_memory_ids,
                   EvalCaseResultRecord.anchor_memory_id).where(EvalCaseResultRecord.run_id.in_(ids))):
        cases.setdefault(str(run_id), []).append({"question": question, "expected_memory_ids": expected, "anchor_memory_id": anchor})
    hashes = {r["run_id"]: run_dataset_hash(cases.get(r["run_id"], [])) for r in runs}
    found = sets_by_hash(session, set(hashes.values()), tenant_id=tenant_id)
    for r in runs:
        r["dataset_hash"] = hashes[r["run_id"]]
        r["question_set"] = found.get(hashes[r["run_id"]])


def get_run(session: Session, run_id: UUID, *, tenant_id: Optional[str]) -> Optional[dict[str, Any]]:
    run = session.execute(_scope(select(EvalRunRecord).where(EvalRunRecord.id == run_id), tenant_id)).scalar_one_or_none()
    if run is None:
        return None
    cases = session.execute(select(EvalCaseResultRecord).where(EvalCaseResultRecord.run_id == run.id).order_by(EvalCaseResultRecord.id)).scalars()
    out = _summary(run)
    out["cases"] = [{**{f: getattr(c, f) for f in CASE_FIELDS}, "expected_memory_ids": c.expected_memory_ids, "anchor_memory_id": c.anchor_memory_id} for c in cases]
    _attach_question_sets(session, [out], tenant_id)
    return out


def _summary(r: EvalRunRecord) -> dict[str, Any]:
    return {
        "run_id": str(r.id), "generated_at": r.created_at.isoformat(), "source": r.source, "trigger": r.trigger,
        "k": r.k, "embedding_model": r.embedding_model, "llm_model": r.llm_model, "commit": r.commit,
        "question_count": r.question_count, "modes_run": r.modes_run, "unavailable_modes": r.unavailable_modes,
        "per_mode": r.per_mode, "failure_taxonomy": r.failure_taxonomy, "persisted": True,
    }
