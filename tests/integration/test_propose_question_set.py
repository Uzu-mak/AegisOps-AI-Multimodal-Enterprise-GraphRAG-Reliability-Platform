"""Proposal files become draft sets resolved to this database's records, marked as proposed, never approved."""
from __future__ import annotations

import json

from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.db.models.memory import MemoryRecord
from app.db.session import SessionLocal
from app.evaluation.datasets import EvalQuestionRecord, EvalQuestionSetRecord
from app.main import app
from app.outbox.models import ProjectionOutboxEvent
from evals.propose_question_set import main


def _wipe():
    with SessionLocal() as s:
        for model in (EvalQuestionRecord, EvalQuestionSetRecord, ProjectionOutboxEvent, MemoryRecord):
            s.execute(delete(model))
        s.commit()


def test_proposal_is_saved_as_a_draft_with_resolved_records(tmp_path):
    _wipe()
    try:
        client = TestClient(app)
        for wo, title in (("100001", "WO 100001: ENGINE IDLE OVERRIDE KILLED ENGINE."), ("100002", "WO 100002: ENGINE IDLE OVERRIDE KILLED ENGINE.")):
            r = client.post("/api/v1/memories", json={"memory_type": "maintenance_action", "title": title, "content": "x",
                                                     "source_type": "work_order", "source_id": wo, "confidence": 0.7, "importance": 0.5})
            assert r.status_code == 201, r.text
        proposal = {"name": "P", "author": "Claude (assistant proposal)", "labeling_method": "assistant-proposed", "questions": [
            {"question": "What fixed the engine that died when someone tried to adjust the idle?", "wo": ["100002", "100001"], "why": "fuel servo"},
            {"question": "What was done after the aircraft was struck by lightning?", "no_answer": True}]}
        f = tmp_path / "p.json"
        f.write_text(json.dumps(proposal))
        assert main([str(f)]) == 0
        sets = client.get("/api/v1/evaluation/question-sets").json()["sets"]
        assert [(s["name"], s["status"], s["created_by"]) for s in sets] == [("P", "draft", "Claude (assistant proposal)")]
        full = client.get(f"/api/v1/evaluation/question-sets/{sets[0]['id']}").json()
        assert {q["labeling_method"] for q in full["questions"]} == {"assistant-proposed"}
        assert len(full["questions"][0]["expected_memory_ids"]) == 2 and full["questions"][1]["expects_no_answer"]

        proposal["name"] = "Q"
        proposal["questions"][0]["wo"] = ["999999"]
        f.write_text(json.dumps(proposal))
        assert main([str(f)]) == 1  # unknown work order: nothing saved
        assert len(client.get("/api/v1/evaluation/question-sets").json()["sets"]) == 1
    finally:
        _wipe()
