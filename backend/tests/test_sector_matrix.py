"""
test_sector_matrix.py — Comprehensive Unit Tests for Phase P2 Taxonomy & Sector Matrix.
"""

import pytest
from app.schemas import (
    EventTaxonomyCategory,
    MacroDriver,
    Sign,
    ExtractedEvent,
    AnalyzeRequest,
)
from app.sector_matrix import (
    classify_event_taxonomy,
    evaluate_macro_drivers,
    compute_dynamic_sector_matrix,
    SECTOR_PROFILES,
)
from app.main import app
from starlette.testclient import TestClient


client = TestClient(app)


class TestTaxonomyClassification:
    def test_monetary_policy_classification(self):
        cat, label = classify_event_taxonomy("RBI hikes repo rate by 25 bps to curb inflation pressures")
        assert cat == EventTaxonomyCategory.monetary_policy
        assert "Monetary" in label

    def test_commodity_shock_classification(self):
        cat, label = classify_event_taxonomy("Brent crude oil surges 12% following Red Sea shipping disruptions")
        assert cat == EventTaxonomyCategory.commodity_shock
        assert "Commodity" in label

    def test_fx_currency_classification(self):
        cat, label = classify_event_taxonomy("Rupee plunges to record low against US dollar amid FII outflows")
        assert cat == EventTaxonomyCategory.fx_currency
        assert "FX" in label or "Currency" in label

    def test_fiscal_policy_classification(self):
        cat, label = classify_event_taxonomy("Union budget announces massive 20% capex boost for railway infrastructure")
        assert cat == EventTaxonomyCategory.fiscal_policy

    def test_classification_with_extracted_event(self):
        event = ExtractedEvent(
            event_type="Policy hike",
            entities=["Repo Rate"],
            direction=Sign.positive,
            region="India",
            evidence_sentence="RBI repo rate raised",
            primary_node="Repo Rate",
        )
        cat, _ = classify_event_taxonomy("Some monetary action text", event)
        assert cat == EventTaxonomyCategory.monetary_policy


class TestMacroDrivers:
    def test_crude_spike_activates_input_cost_and_commodity_pricing(self):
        drivers = evaluate_macro_drivers(
            EventTaxonomyCategory.commodity_shock,
            "Brent crude surges 15% due to geopolitical embargo",
            Sign.positive,
        )
        driver_types = [d.driver for d in drivers]
        assert MacroDriver.commodity_pricing in driver_types
        assert MacroDriver.input_cost in driver_types
        assert all(0.0 <= d.intensity <= 1.0 for d in drivers)

    def test_rate_hike_activates_interest_rates_and_liquidity(self):
        drivers = evaluate_macro_drivers(
            EventTaxonomyCategory.monetary_policy,
            "RBI hikes repo rate by 50 bps",
            Sign.positive,
        )
        driver_types = [d.driver for d in drivers]
        assert MacroDriver.interest_rates in driver_types
        assert MacroDriver.liquidity_availability in driver_types


class TestDynamicSectorMatrix:
    def test_crude_spike_sector_exposure(self):
        event = ExtractedEvent(
            event_type="Commodity spike",
            entities=["Crude Oil"],
            direction=Sign.positive,
            region="Global",
            evidence_sentence="Crude prices surge",
            primary_node="Crude Oil",
        )
        matrix = compute_dynamic_sector_matrix(
            "Brent crude surges 12% after Middle East supply disruption",
            event,
        )
        assert matrix.event_category == EventTaxonomyCategory.commodity_shock
        assert len(matrix.active_drivers) > 0
        
        # Upstream Oil & Gas should be positive (ONGC benefits from higher realization)
        pos_names = [s.sector_name for s in matrix.positive_sectors]
        assert "Upstream Oil & Gas" in pos_names

        # Aviation & Paints should be negative (input cost surge)
        neg_names = [s.sector_name for s in matrix.negative_sectors]
        assert "Aviation & Transport" in neg_names or "Paints & Specialty Chemicals" in neg_names

    def test_rupee_depreciation_sector_exposure(self):
        event = ExtractedEvent(
            event_type="Currency weakness",
            entities=["USD/INR"],
            direction=Sign.positive,  # USD/INR up = weaker rupee
            region="India",
            evidence_sentence="Rupee weakens against dollar",
            primary_node="USD/INR",
        )
        matrix = compute_dynamic_sector_matrix(
            "Rupee falls sharply against the dollar",
            event,
        )
        # IT Services and Pharma should benefit from USD exports
        pos_names = [s.sector_name for s in matrix.positive_sectors]
        assert "IT Services" in pos_names or "Pharmaceuticals" in pos_names

    def test_rate_hike_sector_exposure(self):
        event = ExtractedEvent(
            event_type="Rate hike",
            entities=["Repo Rate"],
            direction=Sign.positive,
            region="India",
            evidence_sentence="Repo rate hiked",
            primary_node="Repo Rate",
        )
        matrix = compute_dynamic_sector_matrix(
            "RBI hikes repo rate by 25 bps to curb inflation",
            event,
        )
        # Real estate should be negatively impacted by higher mortgage rates
        neg_names = [s.sector_name for s in matrix.negative_sectors]
        assert "Real Estate / Construction" in neg_names or "Auto & Ancillaries" in neg_names


class TestAnalyzeEndpointWithSectorMatrix:
    def test_analyze_endpoint_returns_sector_matrix(self):
        resp = client.post(
            "/analyze",
            json={"news_text": "Brent crude surges 12% after Middle East supply disruption", "demo_mode": True},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "sector_matrix" in data
        assert data["sector_matrix"] is not None
        matrix = data["sector_matrix"]
        assert "event_category" in matrix
        assert "active_drivers" in matrix
        assert len(matrix["active_drivers"]) >= 1
        assert "positive_sectors" in matrix
        assert "negative_sectors" in matrix
