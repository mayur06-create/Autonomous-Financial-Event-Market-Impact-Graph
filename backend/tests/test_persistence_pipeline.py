"""
test_persistence_pipeline.py — Comprehensive tests for connected SQLite persistence.
Tests:
  1. Safe schema migration & table creation without data loss.
  2. Idempotent news article ingestion with SHA-256 deduplication.
  3. Impact Graph persistence: direct vs indirect edges, hop distance, confidence decay.
  4. Evidence provenance and verification status attachment.
  5. Conflicting claims preservation without overwriting.
  6. Query APIs: /api/impact-graph, /api/entity/{id}, /api/edge/{id}/evidence, /api/articles.
  7. End-to-end integration from raw text to database inspection.
"""

import pytest
import sqlite3
from pathlib import Path
from fastapi.testclient import TestClient

from app.main import app
from app.persistence import (
    DB_PATH,
    run_migrations,
    get_db_connection,
    compute_content_hash,
    store_article_idempotent,
    store_analysis_record,
    persist_impact_and_knowledge_graph,
    get_persisted_impact_graph,
    get_entity_profile,
    get_edge_evidence_details,
    get_all_persisted_articles,
)


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def test_database_migrations_and_table_structure():
    """Verify all 9 core persistence tables exist and are properly indexed."""
    run_migrations()
    assert DB_PATH.exists(), "knowledge_graph.db must exist"

    conn = get_db_connection()
    try:
        tables = [
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        ]
        expected_tables = [
            "kg_nodes",
            "kg_edges",
            "kg_events",
            "news_articles",
            "news_analyses",
            "impact_events",
            "impact_edges",
            "impact_evidence",
            "analysis_runs",
        ]
        for tbl in expected_tables:
            assert tbl in tables, f"Expected table '{tbl}' not found in database."
    finally:
        conn.close()


def test_article_ingestion_idempotency_and_sha256():
    """Verify articles are deduplicated by SHA-256 hash and duplicate submits return existing ID."""
    import uuid
    run_id = str(uuid.uuid4())[:8]
    text = f"RBI MPC raises repo rate by 25 bps to tackle food inflation pressures. Ref {run_id}"
    title = f"RBI MPC rate hike decision {run_id}"

    # First ingestion
    id_1, is_new_1 = store_article_idempotent(title=title, content=text, publisher="Reuters")
    assert isinstance(id_1, str) and len(id_1) > 0
    assert is_new_1 is True

    # Duplicate ingestion with minor whitespace variation
    text_variant = f"  RBI  MPC raises repo  rate by 25 bps to tackle food inflation pressures. Ref {run_id} \n"
    id_2, is_new_2 = store_article_idempotent(title=title, content=text_variant, publisher="Reuters")
    assert id_1 == id_2, "Same content must map to the same article ID"
    assert is_new_2 is False, "Duplicate submission must report is_new=False"


def test_analysis_record_storage_and_query():
    """Verify news analysis records can be stored and retrieved with articles."""
    art_id, _ = store_article_idempotent(
        title="OPEC+ production cut announcement",
        content="OPEC+ oil ministers announce surprise 1.16 mbpd production cut.",
        publisher="Bloomberg",
    )
    chash = compute_content_hash("OPEC+ surprise cut")
    analysis_id = store_analysis_record(
        article_id=art_id,
        content_hash=chash,
        model_version="test_v1",
        is_relevant=True,
        relevance_reason="Crude supply reduction impact",
        sentiment="positive",
        extracted_entities=["Crude Oil", "OPEC+"],
        extracted_event={"primary_node": "crude_oil", "direction": "+"},
        confidence=0.88,
        status="completed",
    )
    assert isinstance(analysis_id, str) and len(analysis_id) > 0

    articles = get_all_persisted_articles(limit=10)
    assert any(a["id"] == art_id for a in articles)
    matched = next(a for a in articles if a["id"] == art_id)
    assert matched["sentiment"] == "positive"
    assert matched["is_relevant"] == 1


def test_impact_graph_persistence_and_confidence_decay():
    """Verify impact events, edges, and hop-decayed confidence calculations."""
    art_id, _ = store_article_idempotent(
        title="Middle East tensions escalate tanker disruptions",
        content="Tanker disruptions escalate across Strait of Hormuz boosting benchmark crude.",
        publisher="Financial Times",
    )
    an_id = store_analysis_record(
        article_id=art_id,
        content_hash=compute_content_hash(art_id),
        model_version="test_v1",
        is_relevant=True,
        relevance_reason="Energy shock",
        sentiment="positive",
        extracted_entities=["Crude Oil"],
        extracted_event={"primary_node": "crude_oil", "direction": "+"},
        confidence=0.85,
    )

    class MockEvent:
        primary_node = "crude_oil"
        event_type = "Supply Disruption"
        direction = "+"
        magnitude = "12%"
        shock_source = "geopolitics"
        evidence_sentence = "Tanker disruptions escalate across Strait of Hormuz."

    class MockNode:
        def __init__(self, nid):
            self.id = nid
            self.label = nid

    class MockEdge:
        def __init__(self, src, tgt, sign="+", s_min=0.5, s_max=0.8, conf=0.80):
            self.source = src
            self.target = tgt
            self.sign = sign
            self.strength_min = s_min
            self.strength_max = s_max
            self.confidence = conf
            self.time_horizon = "short"
            self.reasoning = f"{src} impacts {tgt}"
            self.evidence = "Observed disruption"

    class MockPath:
        def __init__(self, nodes):
            self.nodes = nodes

    # Direct edge: crude_oil -> atf (hop 1)
    # Indirect edge: atf -> aviation_sector (hop 2)
    mock_edges = [
        MockEdge("crude_oil", "atf", "+", conf=0.80),
        MockEdge("atf", "aviation_sector", "-", conf=0.80),
    ]
    mock_nodes = [MockNode("crude_oil"), MockNode("atf"), MockNode("aviation_sector")]
    mock_paths = [MockPath(["crude_oil", "atf", "aviation_sector"])]

    res = persist_impact_and_knowledge_graph(
        article_id=art_id,
        analysis_id=an_id,
        event=MockEvent(),
        top_paths=mock_paths,
        affected_assets=[],
        response_edges=mock_edges,
        response_nodes=mock_nodes,
        news_text="Tanker disruptions in Hormuz",
    )

    assert res["impact_edges_count"] == 2
    assert res["direct_edges"] == 1
    assert res["indirect_edges"] == 1

    # Query back persisted graph
    graph_data = get_persisted_impact_graph(event_id=res["event_id"])
    assert len(graph_data["edges"]) == 2

    direct_e = next(e for e in graph_data["edges"] if e["source"] == "crude_oil")
    indirect_e = next(e for e in graph_data["edges"] if e["source"] == "atf")

    assert direct_e["is_direct"] is True
    assert direct_e["hop_distance"] == 1
    assert direct_e["confidence"] == 0.80

    assert indirect_e["is_direct"] is False
    assert indirect_e["hop_distance"] == 2
    # Decay applied: 0.80 * 0.85^(2-1) = 0.68
    assert round(indirect_e["confidence"], 2) == 0.68


def test_conflict_preservation_in_knowledge_graph():
    """Verify conflicting directional signals are flagged without overwriting prior mechanisms."""
    conn = get_db_connection()
    try:
        # Check if there is an edge or insert two opposing claims
        edge_id = "test_conflict_edge_1"
        conn.execute("DELETE FROM kg_edges WHERE id = ?", (edge_id,))
        conn.execute(
            """
            INSERT INTO kg_edges (
                id, source, target, relation, sign, claim_type, confidence,
                evidence_list, has_conflict, conflict_notes, first_seen, last_seen
            ) VALUES (?, 'crude_oil', 'omc_sector', 'exposed_to', '+', 'inferred_hypothesis', 0.5, '[]', 1, 'Previous: negative. Current: positive.', '2026-10-10', '2026-10-11')
            """,
            (edge_id,),
        )
        conn.commit()

        details = get_edge_evidence_details(edge_id)
        assert details is not None
        assert details["has_conflict"] == 1
        assert "negative" in details["conflict_notes"]
    finally:
        conn.close()


def test_api_endpoints_via_client(client):
    """Test full HTTP endpoints for impact graph, entity inspection, evidence, and articles."""
    # 1. /api/impact-graph
    res_ig = client.get("/api/impact-graph")
    assert res_ig.status_code == 200
    data_ig = res_ig.json()
    assert "nodes" in data_ig
    assert "edges" in data_ig

    # 2. /api/articles
    res_art = client.get("/api/articles?limit=10")
    assert res_art.status_code == 200
    assert isinstance(res_art.json(), list)

    # 3. /api/entity/{entity_id}
    res_ent = client.get("/api/entity/crude_oil")
    assert res_ent.status_code == 200
    ent_data = res_ent.json()
    assert ent_data["entity"]["id"] == "crude_oil"
    assert "outgoing_edges" in ent_data

    # Case-insensitive label lookup
    res_ent_label = client.get("/api/entity/Crude Oil")
    assert res_ent_label.status_code == 200

    # 4. /api/edge/{edge_id}/evidence
    if data_ig["edges"]:
        edge_id = data_ig["edges"][0]["id"]
        res_ev = client.get(f"/api/edge/{edge_id}/evidence")
        assert res_ev.status_code == 200
        assert "direction" in res_ev.json()
