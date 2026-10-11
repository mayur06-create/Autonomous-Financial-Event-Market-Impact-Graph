"""
test_schemas.py — Unit tests for Pydantic schema validation.  STEP 1 tests.
Run: pytest backend/tests/ -v
"""

import pytest
from pydantic import ValidationError

from app.schemas import (
    AnalyzeRequest,
    Edge,
    EdgeStatus,
    ImpactGraph,
    Lag,
    Node,
    NodeType,
    PathResult,
    SeedEdge,
    Sign,
)


class TestSeedEdge:
    def test_valid_edge(self):
        edge = SeedEdge(
            id="test_e1",
            source="crude_oil",
            target="inflation_cpi",
            sign=Sign.positive,
            strength_range=[0.4, 0.7],
            lag=Lag.short,
            reasoning="Higher crude raises energy prices → CPI",
            source_ref="RBI WP 2022",
        )
        assert edge.id == "test_e1"
        assert edge.sign == Sign.positive

    def test_invalid_range_reversed(self):
        """min > max should raise ValidationError."""
        with pytest.raises(ValidationError):
            SeedEdge(
                id="bad_e",
                source="a",
                target="b",
                sign=Sign.negative,
                strength_range=[0.8, 0.2],  # min > max — invalid
                lag=Lag.immediate,
                reasoning="test",
                source_ref="test",
            )

    def test_invalid_range_out_of_bounds(self):
        """Values outside [0, 1] should raise ValidationError."""
        with pytest.raises(ValidationError):
            SeedEdge(
                id="bad_e2",
                source="a",
                target="b",
                sign=Sign.positive,
                strength_range=[-0.1, 1.2],
                lag=Lag.long,
                reasoning="test",
                source_ref="test",
            )

    def test_ambiguous_sign(self):
        edge = SeedEdge(
            id="ambig",
            source="crude_oil",
            target="omc_sector",
            sign=Sign.ambiguous,
            strength_range=[0.10, 0.60],
            lag=Lag.short,
            reasoning="Govt may absorb shock",
            source_ref="CRISIL 2022",
        )
        assert edge.sign == Sign.ambiguous


class TestNode:
    def test_all_node_types(self):
        for nt in NodeType:
            node = Node(id=f"node_{nt.value}", label="Test Node", type=nt)
            assert node.type == nt

    def test_optional_ticker(self):
        node = Node(id="crude_oil", label="Crude Oil", type=NodeType.commodity)
        assert node.ticker is None


class TestEdge:
    def test_edge_confidence_bounds(self):
        """Confidence must be in [0, 1]."""
        with pytest.raises(ValidationError):
            Edge(
                id="e1", source="a", target="b",
                sign=Sign.positive,
                strength_min=0.3, strength_max=0.7,
                lag=Lag.short,
                reasoning="test",
                status=EdgeStatus.seed,
                confidence=1.5,  # out of bounds
                source_ref="test",
            )


class TestAnalyzeRequest:
    def test_min_length(self):
        with pytest.raises(ValidationError):
            AnalyzeRequest(news_text="short")  # < 50 chars

    def test_valid_request(self):
        text = "A" * 100
        req = AnalyzeRequest(news_text=text, demo_mode=True)
        assert req.demo_mode is True
