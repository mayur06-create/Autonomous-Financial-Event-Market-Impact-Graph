"""
test_market_data.py — Unit Tests for Phase P4 Live Market Data Adapter.
"""

import pytest
from unittest.mock import patch, MagicMock
from app.schemas import LiveQuoteResult
from app.market_data import (
    get_live_quote,
    get_batch_quotes,
    fetch_alphavantage_quote,
    _QUOTE_CACHE,
)
from app.main import app
from starlette.testclient import TestClient

client = TestClient(app)


class TestMarketDataAdapter:
    def test_live_quote_structure(self):
        # Mock yfinance to ensure reliable deterministic test
        mock_quote = LiveQuoteResult(
            ticker="INDIGO.NS",
            price=4500.50,
            change=35.20,
            change_pct=0.79,
            currency="INR",
            timestamp="2026-10-10T12:00:00Z",
            data_status="delayed",
            provider="yfinance",
            high_52w=4800.0,
            low_52w=2900.0,
        )
        with patch("app.market_data.fetch_yfinance_quote", return_value=mock_quote):
            q = get_live_quote("INDIGO.NS", force_refresh=True)
            assert q.ticker == "INDIGO.NS"
            assert q.price == 4500.50
            assert q.provider == "yfinance"
            assert q.data_status in ("delayed", "live", "cached")

    def test_caching_mechanism(self):
        mock_quote = LiveQuoteResult(
            ticker="TCS.NS",
            price=3800.00,
            change=-15.00,
            change_pct=-0.39,
            currency="INR",
            timestamp="2026-10-10T12:00:00Z",
            data_status="delayed",
            provider="yfinance",
        )
        with patch("app.market_data.fetch_yfinance_quote", return_value=mock_quote):
            q1 = get_live_quote("TCS.NS", force_refresh=True)
            assert q1.price == 3800.00
            
            # Second call without force_refresh should hit cache
            q2 = get_live_quote("TCS.NS", force_refresh=False)
            assert q2.data_status == "cached"
            assert "cache" in q2.note.lower()

    def test_alphavantage_unconfigured_without_api_key(self):
        with patch.dict("os.environ", {"ALPHA_VANTAGE_API_KEY": ""}):
            av = fetch_alphavantage_quote("INDIGO.NS")
            assert av.data_status == "unconfigured"
            assert av.price is None
            assert "not configured" in av.note

    def test_batch_quotes(self):
        mock_quote = LiveQuoteResult(
            ticker="HDFCBANK.NS",
            price=1650.00,
            change=10.00,
            change_pct=0.61,
            currency="INR",
            timestamp="2026-10-10T12:00:00Z",
            data_status="delayed",
            provider="yfinance",
        )
        with patch("app.market_data.fetch_yfinance_quote", return_value=mock_quote):
            res = get_batch_quotes(["HDFCBANK.NS", "Nifty Bank"])
            assert len(res) >= 1


class TestMarketAPIEndpoints:
    def test_get_quote_endpoint(self):
        resp = client.get("/market/quote?ticker=INDIGO.NS")
        assert resp.status_code == 200
        data = resp.json()
        assert "ticker" in data
        assert "data_status" in data
        assert "provider" in data

    def test_batch_quotes_endpoint(self):
        resp = client.post(
            "/market/batch-quotes",
            json={"tickers": ["INDIGO.NS", "TCS.NS", "^NSEBANK"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "quotes" in data
        assert "active_count" in data
