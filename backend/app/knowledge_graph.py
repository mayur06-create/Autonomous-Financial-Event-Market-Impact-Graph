"""
knowledge_graph.py — Persistent Cumulative Knowledge Graph Store (SQLite-backed).
Capability 4: Construct AND update cumulative knowledge graph.

Features:
  1. Persistent SQLite storage in backend/app/cache/knowledge_graph.db.
  2. Pre-seeded from curated seed_graph.json if empty.
  3. Merges new analysis events into cumulative graph:
     - Deduplicates nodes & edges by canonical IDs
     - Appends evidence (article quote, source, timestamp, sign)
     - Increments support_count
     - Recomputes confidence with multi-evidence asymptotic boost
     - Detects and flags conflicting evidence (opposing signs) without overwriting
     - Tracks per-event subgraphs for isolated viewing
  4. Querying cumulative graph with filters: node_type, min_confidence, start_date, event_id.
  5. Audit history of updates: "this article added N nodes / M edges / strengthened K edges".
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent / "cache" / "knowledge_graph.db"
SEED_GRAPH_PATH = Path(__file__).parent / "seed_graph.json"


def get_db_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_kg_db(force_reseed: bool = False) -> None:
    """Initialize SQLite tables and populate from seed_graph.json if empty."""
    conn = get_db_connection()
    try:
        with conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS kg_nodes (
                    id TEXT PRIMARY KEY,
                    label TEXT NOT NULL,
                    type TEXT NOT NULL,
                    description TEXT,
                    ticker TEXT,
                    mention_count INTEGER DEFAULT 1,
                    first_seen TEXT NOT NULL,
                    last_seen TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS kg_edges (
                    id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    target TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    sign TEXT NOT NULL,
                    claim_type TEXT NOT NULL,
                    strength_min REAL DEFAULT 0.0,
                    strength_max REAL DEFAULT 1.0,
                    confidence REAL DEFAULT 0.5,
                    support_count INTEGER DEFAULT 1,
                    evidence_list TEXT NOT NULL,
                    has_conflict INTEGER DEFAULT 0,
                    conflict_notes TEXT,
                    first_seen TEXT NOT NULL,
                    last_seen TEXT NOT NULL,
                    FOREIGN KEY(source) REFERENCES kg_nodes(id),
                    FOREIGN KEY(target) REFERENCES kg_nodes(id)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS kg_events (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    news_text TEXT NOT NULL,
                    archetype TEXT NOT NULL,
                    primary_node TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    magnitude TEXT,
                    shock_source TEXT,
                    timestamp TEXT NOT NULL,
                    added_nodes INTEGER DEFAULT 0,
                    added_edges INTEGER DEFAULT 0,
                    strengthened_edges INTEGER DEFAULT 0,
                    conflict_edges INTEGER DEFAULT 0,
                    summary_text TEXT NOT NULL,
                    subgraph_nodes TEXT NOT NULL,
                    subgraph_edges TEXT NOT NULL
                )
            """)

            if force_reseed:
                conn.execute("DELETE FROM kg_edges")
                conn.execute("DELETE FROM kg_nodes")
                conn.execute("DELETE FROM kg_events")

            # Check if seed is needed
            cur = conn.execute("SELECT COUNT(*) AS cnt FROM kg_nodes")
            row = cur.fetchone()
            if row and row["cnt"] == 0 and SEED_GRAPH_PATH.exists():
                _seed_from_file(conn)
    finally:
        conn.close()


def _seed_from_file(conn: sqlite3.Connection) -> None:
    """Load canonical seed graph nodes and edges into persistent store."""
    try:
        raw = json.loads(SEED_GRAPH_PATH.read_text(encoding="utf-8"))
        now_iso = datetime.now(timezone.utc).isoformat()

        nodes = raw.get("nodes", [])
        for n in nodes:
            conn.execute(
                """
                INSERT OR REPLACE INTO kg_nodes (id, label, type, description, ticker, mention_count, first_seen, last_seen)
                VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (n["id"], n["label"], n["type"], n.get("description"), n.get("ticker"), now_iso, now_iso),
            )

        edges = raw.get("edges", [])
        for e in edges:
            lo, hi = e.get("strength_range", [0.4, 0.7])
            eid = f"{e['source']}->{e['target']}"
            evidence = [{
                "article_id": "seed",
                "quote": e.get("reasoning", "Curated causal relationship"),
                "source": e.get("source_ref", "Curated Indian Macro Knowledge Base"),
                "published_at": now_iso,
                "sign": e.get("sign", "+"),
            }]
            conn.execute(
                """
                INSERT OR REPLACE INTO kg_edges (
                    id, source, target, relation, sign, claim_type,
                    strength_min, strength_max, confidence, support_count,
                    evidence_list, has_conflict, conflict_notes, first_seen, last_seen
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, 0, NULL, ?, ?)
                """,
                (
                    eid,
                    e["source"],
                    e["target"],
                    "exposed_to",
                    e.get("sign", "+"),
                    "established_mechanism",
                    lo,
                    hi,
                    round((lo + hi) / 2, 3),
                    json.dumps(evidence),
                    now_iso,
                    now_iso,
                ),
            )
        logger.info("Knowledge Graph pre-seeded with %d nodes and %d edges", len(nodes), len(edges))
    except Exception as exc:
        logger.exception("Failed to seed knowledge graph from file: %s", exc)


def merge_analysis_into_kg(
    event: Any,
    response_nodes: list[Any],
    response_edges: list[Any],
    news_text: str,
    source: str = "Market News",
    published_at: Optional[str] = None,
) -> dict[str, Any]:
    """
    Merges a newly analyzed event into the persistent knowledge graph.
    - Dedupes nodes and updates mention counts.
    - Dedupes edges: appends evidence, increments support_count, recomputes confidence.
    - Detects conflicting edge signs across events and flags them.
    - Persists per-event subgraph.
    - Returns update stats.
    """
    init_kg_db()
    conn = get_db_connection()
    now_iso = datetime.now(timezone.utc).isoformat()
    event_id = str(uuid.uuid4())[:12]
    ev_pub = published_at or now_iso

    added_nodes = 0
    added_edges = 0
    strengthened_edges = 0
    conflict_edges = 0

    subgraph_node_ids = set()
    subgraph_edge_ids = set()

    try:
        with conn:
            # 1. Merge Nodes
            for n in response_nodes:
                nid = getattr(n, "id", None) or n.get("id")
                if not nid or nid.startswith("UNLINKED"):
                    continue
                subgraph_node_ids.add(nid)
                lbl = getattr(n, "label", nid) or nid
                ntype = getattr(n, "type", "sector")
                if hasattr(ntype, "value"):
                    ntype = ntype.value
                desc = getattr(n, "description", None)
                ticker = getattr(n, "ticker", None)

                cur = conn.execute("SELECT id, mention_count FROM kg_nodes WHERE id = ?", (nid,))
                existing_node = cur.fetchone()
                if existing_node:
                    conn.execute(
                        "UPDATE kg_nodes SET mention_count = mention_count + 1, last_seen = ? WHERE id = ?",
                        (now_iso, nid),
                    )
                else:
                    conn.execute(
                        """
                        INSERT INTO kg_nodes (id, label, type, description, ticker, mention_count, first_seen, last_seen)
                        VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                        """,
                        (nid, lbl, str(ntype), desc, ticker, now_iso, now_iso),
                    )
                    added_nodes += 1

            # 2. Merge Edges
            for e in response_edges:
                src = getattr(e, "source", None) or e.get("source")
                tgt = getattr(e, "target", None) or e.get("target")
                if not src or not tgt or src.startswith("UNLINKED") or tgt.startswith("UNLINKED"):
                    continue

                eid = f"{src}->{tgt}"
                subgraph_edge_ids.add(eid)

                sign_val = getattr(e, "sign", "+")
                if hasattr(sign_val, "value"):
                    sign_val = sign_val.value
                rel_val = getattr(e, "relation", "exposed_to") or "exposed_to"
                claim_val = getattr(e, "claim_type", "established_mechanism") or "established_mechanism"
                s_min = float(getattr(e, "strength_min", 0.4) or 0.4)
                s_max = float(getattr(e, "strength_max", 0.7) or 0.7)
                conf = float(getattr(e, "confidence", 0.6) or 0.6)

                ev_quote = getattr(e, "evidence", None)
                if not ev_quote or ev_quote == "not provided":
                    ev_quote = getattr(event, "evidence_sentence", None) or news_text[:200]

                new_evidence_item = {
                    "article_id": event_id,
                    "quote": ev_quote[:300],
                    "source": source,
                    "published_at": ev_pub,
                    "sign": sign_val,
                }

                cur = conn.execute(
                    "SELECT id, sign, confidence, support_count, evidence_list, has_conflict, conflict_notes FROM kg_edges WHERE id = ?",
                    (eid,),
                )
                existing_edge = cur.fetchone()

                if existing_edge:
                    old_sign = existing_edge["sign"]
                    old_conf = float(existing_edge["confidence"] or 0.5)
                    old_support = int(existing_edge["support_count"] or 1)
                    has_conflict = int(existing_edge["has_conflict"] or 0)
                    conflict_notes = existing_edge["conflict_notes"] or ""

                    # Check for conflicting directional signal
                    if old_sign in ("+", "-") and sign_val in ("+", "-") and old_sign != sign_val:
                        has_conflict = 1
                        conflict_edges += 1
                        note_add = f"Opposing sign detected on {now_iso[:10]}: recorded '{old_sign}' vs new '{sign_val}' from \"{ev_quote[:60]}...\""
                        conflict_notes = f"{conflict_notes}; {note_add}".strip("; ")

                    # Append evidence (deduplicating near-identical quote or same event)
                    try:
                        ev_list = json.loads(existing_edge["evidence_list"] or "[]")
                    except Exception:
                        ev_list = []

                    is_duplicate_evidence = any(
                        (ev.get("quote") and ev.get("quote")[:100] == new_evidence_item["quote"][:100]) or
                        (ev.get("article_id") == event_id)
                        for ev in ev_list
                    )

                    if not is_duplicate_evidence:
                        ev_list.append(new_evidence_item)

                    # Distinct news evidence (excluding curated seed entries)
                    news_evidence = [x for x in ev_list if x.get("article_id") != "seed"]
                    new_support = max(1, len(ev_list))

                    # Multi-evidence asymptotic boost: driven by independent news evidence count
                    base_conf = max(old_conf, conf)
                    news_corrob_count = len(news_evidence)
                    boost = min(0.18, 0.04 * max(0, news_corrob_count - 1)) if news_corrob_count > 1 else 0.0
                    penalty = 0.15 if has_conflict else 0.0
                    new_computed_conf = round(max(0.2, min(0.96, base_conf + boost - penalty)), 3)

                    conn.execute(
                        """
                        UPDATE kg_edges
                        SET support_count = ?,
                            confidence = ?,
                            evidence_list = ?,
                            has_conflict = ?,
                            conflict_notes = ?,
                            last_seen = ?,
                            relation = ?
                        WHERE id = ?
                        """,
                        (
                            new_support,
                            new_computed_conf,
                            json.dumps(ev_list),
                            has_conflict,
                            conflict_notes,
                            now_iso,
                            rel_val,
                            eid,
                        ),
                    )
                    strengthened_edges += 1
                else:
                    # New edge
                    ev_list = [new_evidence_item]
                    conn.execute(
                        """
                        INSERT INTO kg_edges (
                            id, source, target, relation, sign, claim_type,
                            strength_min, strength_max, confidence, support_count,
                            evidence_list, has_conflict, conflict_notes, first_seen, last_seen
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, 0, NULL, ?, ?)
                        """,
                        (
                            eid,
                            src,
                            tgt,
                            rel_val,
                            sign_val,
                            claim_val,
                            s_min,
                            s_max,
                            round(conf, 3),
                            json.dumps(ev_list),
                            now_iso,
                            now_iso,
                        ),
                    )
                    added_edges += 1

            # 3. Record Event & Subgraph
            summary_parts = []
            if added_nodes > 0:
                summary_parts.append(f"{added_nodes} node{'s' if added_nodes != 1 else ''} added")
            if added_edges > 0:
                summary_parts.append(f"{added_edges} new edge{'s' if added_edges != 1 else ''} created")
            if strengthened_edges > 0:
                summary_parts.append(f"{strengthened_edges} edge{'s' if strengthened_edges != 1 else ''} strengthened")
            if conflict_edges > 0:
                summary_parts.append(f"[CONFLICT] {conflict_edges} conflict{'s' if conflict_edges != 1 else ''} flagged")
            if not summary_parts:
                summary_parts.append("No graph changes (existing nodes re-verified)")

            summary_text = f"This article: {', '.join(summary_parts)}."

            ev_type = getattr(event, "event_type", "Financial Event")
            ev_arch = getattr(event, "archetype", "macro_shock")
            ev_primary = getattr(event, "primary_node", "unknown")
            ev_dir = getattr(event, "direction", "+")
            if hasattr(ev_dir, "value"):
                ev_dir = ev_dir.value
            ev_mag = getattr(event, "magnitude", None)
            ev_shock = getattr(event, "shock_source", "unclear")

            conn.execute(
                """
                INSERT INTO kg_events (
                    id, title, news_text, archetype, primary_node,
                    direction, magnitude, shock_source, timestamp,
                    added_nodes, added_edges, strengthened_edges, conflict_edges,
                    summary_text, subgraph_nodes, subgraph_edges
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    ev_type,
                    news_text,
                    str(ev_arch),
                    ev_primary,
                    str(ev_dir),
                    ev_mag,
                    str(ev_shock),
                    now_iso,
                    added_nodes,
                    added_edges,
                    strengthened_edges,
                    conflict_edges,
                    summary_text,
                    json.dumps(list(subgraph_node_ids)),
                    json.dumps(list(subgraph_edge_ids)),
                ),
            )

        return {
            "event_id": event_id,
            "added_nodes": added_nodes,
            "added_edges": added_edges,
            "strengthened_edges": strengthened_edges,
            "conflict_edges": conflict_edges,
            "summary_text": summary_text,
            "subgraph_nodes_count": len(subgraph_node_ids),
            "subgraph_edges_count": len(subgraph_edge_ids),
            "timestamp": now_iso,
        }
    except Exception as exc:
        logger.exception("Failed to merge analysis into knowledge graph: %s", exc)
        return {
            "event_id": event_id,
            "added_nodes": 0,
            "added_edges": 0,
            "strengthened_edges": 0,
            "conflict_edges": 0,
            "summary_text": f"KG update error: {exc}",
            "timestamp": now_iso,
        }
    finally:
        conn.close()


def get_cumulative_kg(
    node_type: Optional[str] = None,
    min_confidence: float = 0.0,
    start_date: Optional[str] = None,
    event_id: Optional[str] = None,
) -> dict[str, Any]:
    """
    Retrieve cumulative knowledge graph filtered by node type, minimum confidence,
    date, or isolated to a specific event's subgraph.
    """
    init_kg_db()
    conn = get_db_connection()
    try:
        # If event_id is specified, get its isolated subgraph
        subgraph_nodes = None
        subgraph_edges = None
        event_info = None

        if event_id:
            cur = conn.execute("SELECT * FROM kg_events WHERE id = ?", (event_id,))
            ev_row = cur.fetchone()
            if ev_row:
                event_info = dict(ev_row)
                try:
                    subgraph_nodes = set(json.loads(ev_row["subgraph_nodes"]))
                    subgraph_edges = set(json.loads(ev_row["subgraph_edges"]))
                except Exception:
                    pass

        # Query edges
        edge_query = "SELECT * FROM kg_edges WHERE confidence >= ?"
        edge_params: list[Any] = [min_confidence]

        if start_date:
            edge_query += " AND last_seen >= ?"
            edge_params.append(start_date)

        cur_edges = conn.execute(edge_query, edge_params)
        all_edges = [dict(r) for r in cur_edges.fetchall()]

        # Parse evidence JSON
        filtered_edges = []
        referenced_node_ids = set()

        for e in all_edges:
            if subgraph_edges is not None and e["id"] not in subgraph_edges:
                continue
            try:
                e["evidence_list"] = json.loads(e.get("evidence_list") or "[]")
            except Exception:
                e["evidence_list"] = []
            filtered_edges.append(e)
            referenced_node_ids.add(e["source"])
            referenced_node_ids.add(e["target"])

        # Query nodes
        node_query = "SELECT * FROM kg_nodes WHERE 1=1"
        node_params: list[Any] = []

        if node_type and node_type != "all":
            node_query += " AND type = ?"
            node_params.append(node_type)

        cur_nodes = conn.execute(node_query, node_params)
        all_nodes = [dict(r) for r in cur_nodes.fetchall()]

        filtered_nodes = []
        for n in all_nodes:
            if subgraph_nodes is not None and n["id"] not in subgraph_nodes:
                continue
            # Keep nodes that are connected or if user is filtering explicitly
            if node_type and node_type != "all":
                filtered_nodes.append(n)
            elif n["id"] in referenced_node_ids or subgraph_nodes is not None:
                filtered_nodes.append(n)

        # Filter edges again so no edges refer to missing nodes if node_type filter applied
        if node_type and node_type != "all":
            valid_node_ids = {n["id"] for n in filtered_nodes}
            filtered_edges = [
                e for e in filtered_edges
                if e["source"] in valid_node_ids or e["target"] in valid_node_ids
            ]

        # Stats
        total_nodes = len(filtered_nodes)
        total_edges = len(filtered_edges)
        conflict_count = sum(1 for e in filtered_edges if e.get("has_conflict"))
        avg_confidence = round(
            sum(e.get("confidence", 0) for e in filtered_edges) / max(1, total_edges), 3
        ) if total_edges > 0 else 0.0

        # Type distribution
        type_counts: dict[str, int] = {}
        for n in filtered_nodes:
            t = n.get("type", "other")
            type_counts[t] = type_counts.get(t, 0) + 1

        return {
            "nodes": filtered_nodes,
            "edges": filtered_edges,
            "stats": {
                "total_nodes": total_nodes,
                "total_edges": total_edges,
                "conflict_count": conflict_count,
                "avg_confidence": avg_confidence,
                "type_counts": type_counts,
            },
            "event_filter": event_info,
        }
    finally:
        conn.close()


def get_kg_update_history(limit: int = 15) -> list[dict[str, Any]]:
    """Retrieve list of recent analyses and their graph update summaries."""
    init_kg_db()
    conn = get_db_connection()
    try:
        cur = conn.execute(
            """
            SELECT id, title, archetype, primary_node, direction, magnitude,
                   timestamp, added_nodes, added_edges, strengthened_edges, conflict_edges,
                   summary_text, news_text
            FROM kg_events
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        return rows
    finally:
        conn.close()
