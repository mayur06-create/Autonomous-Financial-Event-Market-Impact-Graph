"""
test_propagation.py — Unit tests for the propagation engine.  STEP 4 tests.
Run: pytest backend/tests/ -v
"""

import pytest

from app.propagation import multiply_signs, propagate, PER_HOP_DECAY
from app.schemas import ExtractedEvent, Sign


class TestSignMultiplication:
    def test_pos_pos(self):
        assert multiply_signs(Sign.positive, Sign.positive) == Sign.positive

    def test_pos_neg(self):
        assert multiply_signs(Sign.positive, Sign.negative) == Sign.negative

    def test_neg_neg(self):
        assert multiply_signs(Sign.negative, Sign.negative) == Sign.positive

    def test_ambiguous_propagates(self):
        assert multiply_signs(Sign.ambiguous, Sign.positive) == Sign.ambiguous
        assert multiply_signs(Sign.positive, Sign.ambiguous) == Sign.ambiguous
        assert multiply_signs(Sign.negative, Sign.ambiguous) == Sign.ambiguous


class TestPropagate:
    """Integration tests using the actual seed graph."""

    def _make_event(self, primary_node: str, direction: Sign = Sign.positive) -> ExtractedEvent:
        return ExtractedEvent(
            event_type        = "test_event",
            entities          = [primary_node],
            direction         = direction,
            magnitude         = None,
            region            = "India",
            evidence_sentence = "Test sentence.",
            primary_node      = primary_node,
            unlinked_entities = [],
        )

    def test_crude_oil_propagates(self):
        """Crude oil should propagate to multiple downstream nodes."""
        event = self._make_event("crude_oil", Sign.positive)
        paths, assets = propagate(event)
        assert len(paths) > 0
        assert len(assets) > 0

        # Expect aviation, inflation, omc to be in affected assets
        asset_ids = {a.node_id for a in assets}
        assert "inflation_cpi" in asset_ids or "atf" in asset_ids

    def test_inr_depreciation_it_positive(self):
        """INR depreciation (direction=+) should positively affect IT sector."""
        event = self._make_event("inr", Sign.positive)
        paths, assets = propagate(event)

        it_assets = [a for a in assets if a.node_id == "it_sector"]
        if it_assets:
            assert it_assets[0].direction == Sign.positive, (
                "IT should benefit from INR depreciation (weaker INR → more INR per USD)"
            )

    def test_repo_rate_hike_nifty_bank_negative(self):
        """Repo rate hike should negatively affect Nifty Bank."""
        event = self._make_event("repo_rate", Sign.positive)
        paths, assets = propagate(event)

        bank_assets = [a for a in assets if a.node_id == "nifty_bank"]
        if bank_assets:
            assert bank_assets[0].direction == Sign.negative, (
                "Nifty Bank should fall on rate hike (NIM compression)"
            )

    def test_unlinked_node_returns_empty(self):
        """Propagation from an unlinked node should return empty results."""
        event = self._make_event("UNLINKED:unknown_company")
        paths, assets = propagate(event)
        assert paths == []
        assert assets == []

    def test_path_score_decreases_with_hops(self):
        """Longer paths should have lower scores due to decay."""
        event = self._make_event("crude_oil", Sign.positive)
        paths, _ = propagate(event)

        if len(paths) >= 2:
            # Paths are sorted by score descending; 1-hop paths should outrank 4-hop
            one_hop  = [p for p in paths if p.hop_count == 1]
            four_hop = [p for p in paths if p.hop_count >= 4]
            if one_hop and four_hop:
                assert one_hop[0].path_score >= four_hop[0].path_score

    def test_cycle_prevention(self):
        """No path should contain a repeated node."""
        event = self._make_event("inflation_cpi", Sign.positive)
        paths, _ = propagate(event)
        for path in paths:
            assert len(path.nodes) == len(set(path.nodes)), (
                f"Cycle detected in path: {path.nodes}"
            )


class TestGraphLoader:
    def test_seed_graph_loads(self):
        """Seed graph should load and validate without errors."""
        from app.graph_loader import load_seed_graph
        sg = load_seed_graph()
        assert len(sg.nodes) >= 30
        assert len(sg.edges) >= 45

    def test_alias_resolution(self):
        """Known aliases should resolve to canonical node IDs."""
        from app.graph_loader import resolve_alias
        assert resolve_alias("brent") == "crude_oil"
        assert resolve_alias("banknifty") == "nifty_bank"
        assert resolve_alias("cpi") == "inflation_cpi"
        assert resolve_alias("rupee") == "inr"
        assert resolve_alias("completely_unknown_entity_xyz") is None
