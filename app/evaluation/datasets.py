"""
Versioned, reviewed evaluation question sets.

A set is named and versioned. A version moves draft -> in_review -> approved
(or back to draft when returned), and approved versions can later be retired.
Only drafts can be edited; changing an approved set means a new draft version
that records its parent. Each version carries a content hash over its
questions, labels and starting records, so a saved run can be matched to the
exact version it measured (same hash = same questions and labels).

Users are on hold, so the reviewer is an attested name, not a verified login.
In token mode only administrators may approve or return a set.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Iterable, Optional
from uuid import UUID, uuid4

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, Uuid, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.db.base import Base

_JSON = JSON().with_variant(JSONB(), "postgresql")
STATUSES = ("draft", "in_review", "approved", "retired")
LEAK_THRESHOLD = 0.6  # same rule as the console (lib/evalmath.js)


class EvalQuestionSetRecord(Base):
    __tablename__ = "eval_question_set"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_id: Mapped[Optional[UUID]] = mapped_column(Uuid, ForeignKey("eval_question_set.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    review_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    history: Mapped[list] = mapped_column(_JSON, nullable=False, default=list)  # status changes, oldest first


class EvalQuestionRecord(Base):
    __tablename__ = "eval_question"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    set_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("eval_question_set.id", ondelete="CASCADE"), nullable=False, index=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    expected_memory_ids: Mapped[list] = mapped_column(_JSON, nullable=False, default=list)
    anchor_memory_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    expects_no_answer: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    leaked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    labeling_method: Mapped[str] = mapped_column(String(40), nullable=False, default="console")
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class QuestionSetError(ValueError):
    """A request that the set's state does not allow (HTTP 409/422)."""


# ------------------------------------------------------------------ hashing

def dataset_hash(questions: Iterable[dict[str, Any]]) -> str:
    """Order-independent hash of questions, their labels and starting records."""
    rows = sorted(
        (" ".join(str(q["question"]).split()), sorted(str(m) for m in q.get("expected_memory_ids") or []), str(q.get("anchor_memory_id") or ""))
        for q in questions
    )
    return hashlib.sha256(json.dumps(rows).encode()).hexdigest()


def run_dataset_hash(cases: Iterable[dict[str, Any]]) -> str:
    """The same hash computed from a saved run's cases (one entry per question)."""
    seen: dict[str, dict[str, Any]] = {}
    for c in cases:
        seen.setdefault(c["question"], c)
    return dataset_hash(seen.values())


_WORD = re.compile(r"[a-z0-9]+")


def leaks(question: str, titles: Iterable[str]) -> bool:
    """A question that repeats a relevant record's title (or the console prefix) gives the answer away."""
    if re.match(r"^\s*what do we know about:", question, re.I):
        return True
    q = set(_WORD.findall(question.lower()))
    for t in titles:
        tw = set(_WORD.findall((t or "").lower()))
        if tw and len(q & tw) / len(tw) >= LEAK_THRESHOLD:
            return True
    return False


# --------------------------------------------------------------- operations

def _scope(stmt, tenant_id: Optional[str]):
    return stmt.where(EvalQuestionSetRecord.tenant_id == tenant_id) if tenant_id is not None else stmt


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _questions(session: Session, set_id: UUID) -> list[EvalQuestionRecord]:
    return list(session.execute(select(EvalQuestionRecord).where(EvalQuestionRecord.set_id == set_id).order_by(EvalQuestionRecord.position)).scalars())


def _q_out(q: EvalQuestionRecord) -> dict[str, Any]:
    return {"question": q.question, "expected_memory_ids": q.expected_memory_ids, "anchor_memory_id": q.anchor_memory_id,
            "expects_no_answer": q.expects_no_answer, "leaked": q.leaked, "labeling_method": q.labeling_method, "note": q.note}


def _set_out(s: EvalQuestionSetRecord, questions: Optional[list[EvalQuestionRecord]] = None, count: Optional[int] = None) -> dict[str, Any]:
    iso = lambda d: d.isoformat() if d else None  # noqa: E731
    out = {"id": str(s.id), "name": s.name, "version": s.version, "parent_id": str(s.parent_id) if s.parent_id else None,
           "status": s.status, "content_hash": s.content_hash, "created_at": iso(s.created_at), "created_by": s.created_by,
           "submitted_at": iso(s.submitted_at), "reviewed_by": s.reviewed_by, "reviewed_at": iso(s.reviewed_at),
           "review_note": s.review_note, "history": s.history or []}
    if questions is not None:
        out["questions"] = [_q_out(q) for q in questions]
        out["question_count"] = len(questions)
    elif count is not None:
        out["question_count"] = count
    return out


def _write_questions(session: Session, set_id: UUID, questions: list[dict[str, Any]], titles: dict[str, str]) -> str:
    for q in _questions(session, set_id):
        session.delete(q)
    session.flush()
    for i, q in enumerate(questions):
        expected = [str(m) for m in q.get("expected_memory_ids") or []]
        no_answer = bool(q.get("expects_no_answer"))
        if no_answer and expected:
            raise QuestionSetError(f"'{q['question'][:60]}' is marked as having no answer but lists expected records")
        if not no_answer and not expected:
            raise QuestionSetError(f"'{q['question'][:60]}' needs at least one expected record, or mark it as having no answer")
        session.add(EvalQuestionRecord(
            set_id=set_id, position=i, question=" ".join(str(q["question"]).split()), expected_memory_ids=expected,
            anchor_memory_id=str(q["anchor_memory_id"]) if q.get("anchor_memory_id") else None, expects_no_answer=no_answer,
            leaked=leaks(q["question"], [titles.get(m, "") for m in expected]),
            labeling_method=str(q.get("labeling_method") or "console")[:40], note=q.get("note")))
    return dataset_hash(questions)


def create_version(session: Session, *, name: str, questions: list[dict[str, Any]], author: str, titles: dict[str, str],
                   tenant_id: Optional[str]) -> dict[str, Any]:
    """New draft: version 1 of a new name, or the next version of an existing one."""
    name = " ".join(name.split())
    if not name:
        raise QuestionSetError("A question set needs a name")
    latest = session.execute(_scope(select(EvalQuestionSetRecord).where(EvalQuestionSetRecord.name == name), tenant_id)
                             .order_by(EvalQuestionSetRecord.version.desc()).limit(1)).scalar_one_or_none()
    if latest is not None and latest.status == "draft":
        raise QuestionSetError(f"'{name}' already has a draft (version {latest.version}); edit that draft instead")
    s = EvalQuestionSetRecord(tenant_id=tenant_id, name=name, version=(latest.version + 1) if latest else 1,
                              parent_id=latest.id if latest else None, status="draft", content_hash="", created_by=author,
                              history=[{"status": "draft", "by": author, "at": _now().isoformat()}])
    session.add(s)
    session.flush()
    s.content_hash = _write_questions(session, s.id, questions, titles)
    session.commit()
    return _set_out(s, _questions(session, s.id))


def get_set(session: Session, set_id: UUID, *, tenant_id: Optional[str]) -> Optional[dict[str, Any]]:
    s = session.execute(_scope(select(EvalQuestionSetRecord).where(EvalQuestionSetRecord.id == set_id), tenant_id)).scalar_one_or_none()
    return None if s is None else _set_out(s, _questions(session, s.id))


def list_sets(session: Session, *, tenant_id: Optional[str]) -> list[dict[str, Any]]:
    counts = dict(session.execute(select(EvalQuestionRecord.set_id, func.count()).group_by(EvalQuestionRecord.set_id)).all())
    rows = session.execute(_scope(select(EvalQuestionSetRecord), tenant_id)
                           .order_by(EvalQuestionSetRecord.name, EvalQuestionSetRecord.version.desc())).scalars()
    return [_set_out(s, count=counts.get(s.id, 0)) for s in rows]


def _load(session: Session, set_id: UUID, tenant_id: Optional[str]) -> EvalQuestionSetRecord:
    s = session.execute(_scope(select(EvalQuestionSetRecord).where(EvalQuestionSetRecord.id == set_id), tenant_id)).scalar_one_or_none()
    if s is None:
        raise LookupError("Question set not found")
    return s


def replace_questions(session: Session, set_id: UUID, *, questions: list[dict[str, Any]], titles: dict[str, str],
                      tenant_id: Optional[str]) -> dict[str, Any]:
    s = _load(session, set_id, tenant_id)
    if s.status != "draft":
        raise QuestionSetError(f"Version {s.version} is {s.status.replace('_', ' ')} and can't be edited; start a new version")
    s.content_hash = _write_questions(session, s.id, questions, titles)
    session.commit()
    return _set_out(s, _questions(session, s.id))


def transition(session: Session, set_id: UUID, *, action: str, by: str, note: Optional[str], tenant_id: Optional[str]) -> dict[str, Any]:
    """submit (draft -> in_review), approve / return (in_review -> approved / draft), retire (approved -> retired)."""
    s = _load(session, set_id, tenant_id)
    allowed = {"submit": ("draft", "in_review"), "approve": ("in_review", "approved"),
               "return": ("in_review", "draft"), "retire": ("approved", "retired")}
    if action not in allowed:
        raise QuestionSetError(f"Unknown action {action}")
    frm, to = allowed[action]
    if s.status != frm:
        raise QuestionSetError(f"Can't {action} a set that is {s.status.replace('_', ' ')}")
    by = " ".join((by or "").split())
    if not by:
        raise QuestionSetError("Say who is doing this")
    if action == "submit" and not _questions(session, s.id):
        raise QuestionSetError("Add questions before submitting for review")
    if action in ("approve", "return"):
        if by.casefold() == s.created_by.casefold():
            raise QuestionSetError("The reviewer must be someone other than the author")
        s.reviewed_by, s.reviewed_at, s.review_note = by, _now(), note
    if action == "submit":
        s.submitted_at = _now()
    s.status = to
    s.history = [*(s.history or []), {"status": to, "action": action, "by": by, "at": _now().isoformat(), **({"note": note} if note else {})}]
    session.commit()
    return _set_out(s, _questions(session, s.id))


def sets_by_hash(session: Session, hashes: set[str], *, tenant_id: Optional[str]) -> dict[str, dict[str, Any]]:
    """Question-set versions whose content matches these hashes (approved preferred)."""
    if not hashes:
        return {}
    rank = {"approved": 0, "in_review": 1, "retired": 2, "draft": 3}
    out: dict[str, dict[str, Any]] = {}
    for s in session.execute(_scope(select(EvalQuestionSetRecord).where(EvalQuestionSetRecord.content_hash.in_(hashes)), tenant_id)).scalars():
        cur = out.get(s.content_hash)
        if cur is None or rank[s.status] < rank[cur["status"]]:
            out[s.content_hash] = {"id": str(s.id), "name": s.name, "version": s.version, "status": s.status, "reviewed_by": s.reviewed_by}
    return out
