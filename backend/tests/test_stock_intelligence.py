"""
test_stock_intelligence.py — Comprehensive Unit Tests for Phase P3 Stock Intelligence.
"""

import pytest
from app.schemas import (
    ExtractedEvent,
    Sign,
)
from app.sector_matrix import compute_dynamic_sector_matrix
from app.stock_intelligence import (
    evaluate_constituent_exposures,
    STOCK_UNIVERSE,
)
from app.main import app
from starlette.testclient import TestClient

client = TestClient(app)


class TestStockIntelligenceEngine:
    def test_crude_oil_spike_constituent_exposures(self):
        event = ExtractedEvent(
            event_type="Commodity spike",
            entities=["Crude Oil"],
            direction=Sign.positive,
            region="Global",
            evidence_sentence="Brent crude surges 12%",
            primary_node="Crude Oil",
        )
        matrix = compute_dynamic_sector_matrix(
            "Brent crude surges 12% after Middle East supply disruption",
            event,
        )
        report = evaluate_constituent_exposures(
            "Brent crude surges 12% after Middle East supply disruption",
            event,
            matrix,
        )

        assert report.total_stocks_analyzed >= 10
        assert len(report.top_beneficiaries) > 0
        assert len(report.top_pressured) > 0

        # ONGC should be a top beneficiary
        beneficiary_symbols = [b.symbol for b in report.top_beneficiaries]
        assert "ONGC" in beneficiary_symbols

        # IndiGo (fuel opex), BPCL (OMC under-recovery), Asian Paints (crude raw materials) should be pressured
        pressured_symbols = [p.symbol for p in report.top_pressured]
        assert "INDIGO" in pressured_symbols or "BPCL" in pressured_symbols or "ASIANPAINT" in pressured_symbols

    def test_rupee_depreciation_constituent_exposures(self):
        event = ExtractedEvent(
            event_type="Currency weakness",
            entities=["USD/INR"],
            direction=Sign.positive,  # USD/INR up = weaker rupee
            region="India",
            evidence_sentence="Rupee drops against dollar",
            primary_node="USD/INR",
        )
        matrix = compute_dynamic_sector_matrix(
            "Rupee falls sharply against the dollar",
            event,
        )
        report = evaluate_constituent_exposures(
            "Rupee falls sharply against the dollar",
            event,
            matrix,
        )

        # TCS and Infosys should be key beneficiaries
        beneficiary_symbols = [b.symbol for b in report.top_beneficiaries]
        assert "TCS" in beneficiary_symbols or "INFY" in beneficiary_symbols

    def test_rate_hike_constituent_exposures(self):
        event = ExtractedEvent(
            event_type="Monetary tightening",
            entities=["Repo Rate"],
            direction=Sign.positive,
            region="India",
            evidence_sentence="RBI hikes repo rate",
            primary_node="Repo Rate",
        )
        matrix = compute_dynamic_sector_matrix(
            "RBI hikes repo rate by 25 bps to curb inflation",
            event,
        )
        report = evaluate_constituent_exposures(
            "RBI hikes repo rate by 25 bps to curb inflation",
            event,
            matrix,
        )

        # Rate-sensitive DLF (real estate) or Maruti (vehicle financing) should be pressured
        pressured_symbols = [p.symbol for p in report.top_pressured]
        assert "DLF" in pressured_symbols or "MARUTI" in pressured_symbols


class TestAnalyzeEndpointWithStockIntelligence:
    def test_analyze_endpoint_returns_stock_intelligence(self):
        resp = client.post(
            "/analyze",
            json={"news_text": "Brent crude surges 12% after Middle East supply disruption", "demo_mode": True},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "stock_intelligence" in data
        assert data["stock_intelligence"] is not None
        si = data["stock_intelligence"]
        assert "total_stocks_analyzed" in si
        assert si["total_stocks_analyzed"] >= 10
        assert "top_beneficiaries" in si
        assert "top_pressured" in si
        assert len(si["top_beneficiaries"]) > 0
        assert len(si["top_pressured"]) > 0
