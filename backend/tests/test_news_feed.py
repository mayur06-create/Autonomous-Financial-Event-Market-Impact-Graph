"""
test_news_feed.py — Unit tests for Phase P1 Dynamic News & Relevance Gating.
Run: pytest tests/test_news_feed.py -v
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.news_feed import check_market_relevance, get_live_news_feed, search_news_feed, fetch_url_content


client = TestClient(app)


class TestRelevanceGate:
    def test_market_relevant_headlines(self):
        """Relevant economic and financial articles must pass the gate."""
        samples = [
            "RBI increases benchmark repo rate by 25 basis points amid persistent food inflation.",
            "Brent crude oil prices jump 6% following OPEC supply reduction announcement.",
            "Indian rupee depreciates against the US dollar to 84.50 amid foreign investor outflows.",
            "TCS announces major multi-million dollar cloud migration deal with European banking client.",
            "Union Budget increases capital expenditure outlay for railway and highway infrastructure.",
        ]
        for s in samples:
            is_rel, reason, score, entities = check_market_relevance(s)
            assert is_rel is True, f"Failed for: {s}"
            assert score > 0.15
            assert "Market relevant" in reason

    def test_irrelevant_headlines(self):
        """Non-market headlines must be gated out with clear reasons."""
        samples = [
            "Local high school football team won championship 3-0 in thrilling penalty shootout.",
            "Celebrity couple spotted having dinner at Italian restaurant during summer vacation.",
            "New recipe for homemade vanilla chocolate cake with strawberry frosting topping.",
            "Astronomers discover distant galaxy cluster using deep space infrared observatory telescope.",
        ]
        for s in samples:
            is_rel, reason, score, entities = check_market_relevance(s)
            assert is_rel is False, f"Should be irrelevant: {s}"
            assert "No clear market impact" in reason

    def test_short_text_relevance(self):
        is_rel, reason, score, _ = check_market_relevance("hi")
        assert is_rel is False
        assert score == 0.0


class TestLiveFeed:
    def test_live_feed_items(self):
        feed = get_live_news_feed(limit=5)
        assert len(feed) > 0
        for item in feed:
            assert item.title
            assert item.source
            assert item.published_at
            assert item.relevance_score >= 0.0

    def test_search_feed(self):
        results = search_news_feed("crude", limit=5)
        assert isinstance(results, list)


class TestNewsAPIEndpoints:
    def test_get_live_news_endpoint(self):
        resp = client.get("/news/live?limit=5")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] > 0
        assert len(data["items"]) > 0

    def test_get_suggested_news_endpoint(self):
        resp = client.get("/news/suggested?limit=4")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] <= 4

    def test_search_news_endpoint(self):
        resp = client.get("/news/search?q=rbi")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["items"], list)

    def test_analyze_irrelevant_gated(self):
        """Non-market text should return an empty graph with is_relevant=False."""
        text = "The local municipal gardening club hosted an annual tulip and sunflower flower competition today."
        resp = client.post("/analyze", json={"news_text": text, "demo_mode": False})
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_relevant"] is False
        assert "No clear market impact" in data["relevance_reason"]
        assert len(data["nodes"]) == 0
        assert len(data["edges"]) == 0

    def test_fetch_url_invalid(self):
        resp = client.post("/news/fetch-url", json={"url": "not-a-valid-url"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["error"] is not None
        assert data["is_relevant"] is False
