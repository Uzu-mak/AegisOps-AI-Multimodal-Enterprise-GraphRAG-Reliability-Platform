"""Tests for memory promotion policy."""
from app.memory.candidate import MemoryCandidate
from app.memory.promotion import RulesBasedPromotion


class TestRulesBasedPromotion:

    def test_promotes_when_thresholds_met(self):
        policy = RulesBasedPromotion(min_confidence=0.6, min_importance=0.4)
        candidate = MemoryCandidate(
            title="Bearing wear detected",
            content="Elevated vibration signature consistent with bearing wear.",
            confidence=0.8,
            importance=0.7,
        )
        assert policy.should_promote(candidate) is True

    def test_rejects_low_confidence(self):
        policy = RulesBasedPromotion(min_confidence=0.6, min_importance=0.4)
        candidate = MemoryCandidate(
            title="Observation",
            content="Some content",
            confidence=0.3,
            importance=0.7,
        )
        assert policy.should_promote(candidate) is False

    def test_rejects_low_importance(self):
        policy = RulesBasedPromotion(min_confidence=0.6, min_importance=0.4)
        candidate = MemoryCandidate(
            title="Observation",
            content="Some content",
            confidence=0.9,
            importance=0.1,
        )
        assert policy.should_promote(candidate) is False

    def test_rejects_empty_content(self):
        policy = RulesBasedPromotion()
        candidate = MemoryCandidate(
            title="Observation", content="", confidence=0.9, importance=0.9
        )
        assert policy.should_promote(candidate) is False

    def test_rejects_empty_title(self):
        policy = RulesBasedPromotion()
        candidate = MemoryCandidate(
            title="", content="Content here", confidence=0.9, importance=0.9
        )
        assert policy.should_promote(candidate) is False

    def test_build_create_data_maps_fields(self):
        policy = RulesBasedPromotion()
        candidate = MemoryCandidate(
            memory_type="observation",
            title="Test Title",
            content="Test Content",
            source_type="sensor",
            asset_id="pump-1",
            confidence=0.85,
            importance=0.75,
            promotion_reason="High confidence observation",
        )
        create_data = policy.build_create_data(candidate)
        assert create_data.title == "Test Title"
        assert create_data.content == "Test Content"
        assert create_data.confidence == 0.85
        assert create_data.asset_id == "pump-1"
        assert "promotion_reason" in create_data.memory_metadata
