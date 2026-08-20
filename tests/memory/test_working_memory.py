"""Tests for working memory."""
from app.memory.working import WorkingMemory, WorkingMemoryItem


class TestWorkingMemoryBounds:

    def test_add_items(self):
        wm = WorkingMemory(max_items=5)
        wm.add_observation("obs 1")
        wm.add_observation("obs 2")
        assert len(wm) == 2

    def test_evicts_oldest_at_capacity(self):
        wm = WorkingMemory(max_items=3)
        for i in range(5):
            wm.add_observation(f"obs {i}")
        items = wm.get_all()
        assert len(items) == 3
        assert items[0].content == "obs 2"
        assert items[-1].content == "obs 4"

    def test_clear(self):
        wm = WorkingMemory()
        wm.add_observation("something")
        wm.clear()
        assert len(wm) == 0

    def test_get_by_type(self):
        wm = WorkingMemory()
        wm.add_observation("obs")
        wm.add(WorkingMemoryItem(item_type="hypothesis", content="hypothesis"))
        obs = wm.get_by_type("observation")
        hyp = wm.get_by_type("hypothesis")
        assert len(obs) == 1
        assert len(hyp) == 1

    def test_add_evidence_stores_memory_ids(self):
        from uuid import uuid4
        wm = WorkingMemory()
        ids = [uuid4(), uuid4()]
        item = wm.add_evidence("evidence text", evidence_memory_ids=ids)
        assert item.evidence_memory_ids == ids
        assert item.item_type == "retrieved_evidence"

    def test_repr(self):
        wm = WorkingMemory(max_items=10)
        assert "10" in repr(wm)
