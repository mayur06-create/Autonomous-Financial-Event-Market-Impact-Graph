import json
import pathlib
import pytest
from fastapi.testclient import TestClient
from backend.main import app
from backend import schemas

client = TestClient(app)

def test_health():
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["mode"] in ("llm", "fallback")
    assert data["nodes"] > 0
    assert data["edges"] > 0
    schemas.HealthResponse(**data)

def test_demo_events():
    res = client.get("/demo-events")
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)
    assert len(data) >= 3
    assert data[0]["name"] == "Crude spike"

def test_get_graph():
    res = client.get("/graph")
    assert res.status_code == 200
    data = res.json()
    assert "nodes" in data
    assert "edges" in data
    assert "graph_size" in data
    assert data["graph_size"]["nodes"] > 0

def test_reset():
    res = client.post("/reset")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "reset"
    schemas.ResetResponse(**data)

def test_static_routes():
    res_dash = client.get("/")
    assert res_dash.status_code == 200
    assert "ImpactGraph" in res_dash.text

    res_legacy = client.get("/legacy")
    assert res_legacy.status_code == 200
    assert "Market Impact Graph" in res_legacy.text

def test_analyze_demo_events():
    demo_path = pathlib.Path(__file__).parent / "demo_events.json"
    cases = json.loads(demo_path.read_text(encoding="utf-8"))

    for c in cases:
        # Reset before each case to test fresh independent analysis
        client.post("/reset")
        res = client.post("/analyze", json={"text": c["news"]})
        assert res.status_code == 200, f"Failed on {c['name']}: {res.text}"
        data = res.json()

        # Validate against strict Pydantic model
        validated = schemas.AnalyzeResponse(**data)

        # Check required task fields
        assert validated.event.headline == c["news"]
        assert validated.start_node == c["start"]
        assert validated.mode in ("llm", "fallback")
        assert len(validated.nodes) > 0
        assert len(validated.edges) > 0
        assert len(validated.top_paths) > 0
        assert len(validated.affected_assets) > 0

        # Check KPIs
        assert validated.kpis.assets_affected == len(validated.affected_assets)
        assert validated.kpis.chains_traced > 0
        assert validated.kpis.avg_confidence >= 0.0

        # Check oracle expected signs
        got_impacts = {a.name: a.impact for a in validated.affected_assets}
        for asset, expected_sign in c["expect"].items():
            assert asset in got_impacts, f"Missing asset {asset} in {c['name']}"
            assert got_impacts[asset] == expected_sign, (
                f"Asset {asset} expected sign {expected_sign:+d} but got {got_impacts[asset]:+d}"
            )

def test_analyze_invalid_headline():
    res = client.post("/analyze", json={"text": "completely unrelated text about bananas and apples"})
    assert res.status_code == 400
    assert "error" in res.json().get("detail", "").lower() or "identify" in res.json().get("detail", "").lower()
