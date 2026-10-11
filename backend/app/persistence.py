"""
persistence.py — Safe incremental SQLite persistence and connected Graph Store.
Handles:
  - Automated schema migration with backup validation.
  - Storage of news articles with SHA-256 deduplication and idempotent processing.
  - Linked storage of news analyses, impact events, impact edges, and impact evidence.
  - Full provenance, verification status, and conflict preservation.
  - Distinguishes direct impacts from indirect/propagated impacts.
  - Clean query APIs for impact graph, entity inspection, and evidence tracking.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("market_impact.persistence")

DB_PATH = Path(__file__).parent / "cache" / "knowledge_graph.db"
BACKUP_PATH = Path(__file__).parent / "cache" / "knowledge_graph.db.backup"


def get_db_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def compute_content_hash(text: str) -> str:
    """Normalize whitespace and compute SHA-256 content hash."""
    normalized = re.sub(r"\s+", " ", text.strip().lower())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def run_migrations() -> None:
    """
    Applies safe incremental migrations without dropping tables or losing existing records.
    Pre-backs up DB if it exists and hasn't been backed up yet.
    """
    if DB_PATH.exists() and not BACKUP_PATH.exists():
        try:
            shutil.copy2(str(DB_PATH), str(BACKUP_PATH))
            logger.info("Created pre-migration backup at %s", BACKUP_PATH)
        except Exception as exc:
            logger.warning("Could not create automatic backup: %s", exc)

    conn = get_db_connection()
    try:
        with conn:
            # 1. Base Knowledge Graph tables (preserve legacy structure)
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

            # Safe column additions to kg_edges for provenance & superseding
            cur = conn.execute("PRAGMA table_info(kg_edges)")
            existing_cols = {row["name"] for row in cur.fetchall()}

            if "verification_status" not in existing_cols:
                conn.execute("ALTER TABLE kg_edges ADD COLUMN verification_status TEXT DEFAULT 'established_mechanism'")
            if "superseded_by" not in existing_cols:
                conn.execute("ALTER TABLE kg_edges ADD COLUMN superseded_by TEXT DEFAULT NULL")
            if "is_active" not in existing_cols:
                conn.execute("ALTER TABLE kg_edges ADD COLUMN is_active INTEGER DEFAULT 1")
            if "provenance" not in existing_cols:
                conn.execute("ALTER TABLE kg_edges ADD COLUMN provenance TEXT DEFAULT '[]'")

            # 2. news_articles (idempotent ingestion store)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS news_articles (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    publisher TEXT DEFAULT 'Market News',
                    url TEXT,
                    published_at TEXT NOT NULL,
                    content TEXT NOT NULL,
                    content_hash TEXT UNIQUE NOT NULL,
                    ingestion_status TEXT DEFAULT 'ingested',
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_articles_hash ON news_articles(content_hash)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_articles_pub ON news_articles(published_at)")

            # 3. news_analyses (tracked extraction results)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS news_analyses (
                    id TEXT PRIMARY KEY,
                    article_id TEXT NOT NULL REFERENCES news_articles(id),
                    content_hash TEXT NOT NULL,
                    model_version TEXT NOT NULL,
                    status TEXT DEFAULT 'completed',
                    is_relevant INTEGER DEFAULT 1,
                    relevance_reason TEXT,
                    sentiment TEXT DEFAULT 'mixed',
                    extracted_entities TEXT NOT NULL,
                    extracted_event TEXT NOT NULL,
                    confidence REAL DEFAULT 0.5,
                    error_message TEXT,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_analyses_article ON news_analyses(article_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_analyses_hash ON news_analyses(content_hash)")

            # 4. impact_events (root event trigger)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS impact_events (
                    id TEXT PRIMARY KEY,
                    analysis_id TEXT REFERENCES news_analyses(id),
                    article_id TEXT REFERENCES news_articles(id),
                    event_type TEXT NOT NULL,
                    primary_node TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    magnitude TEXT,
                    shock_source TEXT,
                    evidence_sentence TEXT,
                    timestamp TEXT NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_impact_events_primary ON impact_events(primary_node)")

            # 5. impact_edges (direct and propagated causal impacts)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS impact_edges (
                    id TEXT PRIMARY KEY,
                    event_id TEXT NOT NULL REFERENCES impact_events(id),
                    source TEXT NOT NULL,
                    target TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    category TEXT NOT NULL,
                    is_direct INTEGER DEFAULT 1,
                    hop_distance INTEGER DEFAULT 1,
                    strength_min REAL DEFAULT 0.4,
                    strength_max REAL DEFAULT 0.7,
                    confidence REAL DEFAULT 0.5,
                    time_horizon TEXT DEFAULT 'short',
                    explanation TEXT,
                    evidence_text TEXT,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_impact_edges_event ON impact_edges(event_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_impact_edges_nodes ON impact_edges(source, target)")

            # 6. impact_evidence (fine-grained quotes and verification status)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS impact_evidence (
                    id TEXT PRIMARY KEY,
                    edge_id TEXT NOT NULL REFERENCES impact_edges(id),
                    article_id TEXT REFERENCES news_articles(id),
                    quote TEXT NOT NULL,
                    source TEXT DEFAULT 'Market News',
                    published_at TEXT NOT NULL,
                    verification_status TEXT DEFAULT 'verified_news_fact',
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_impact_evidence_edge ON impact_evidence(edge_id)")

            # 7. analysis_runs (auditable processing log)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS analysis_runs (
                    id TEXT PRIMARY KEY,
                    article_id TEXT,
                    run_type TEXT DEFAULT 'full_pipeline',
                    status TEXT DEFAULT 'success',
                    duration_ms REAL,
                    error TEXT,
                    created_at TEXT NOT NULL
                )
            """)

        logger.info("Database migrations successfully executed.")
    finally:
        conn.close()


# ── Ingestion & Idempotency ───────────────────────────────────────────────────

def store_article_idempotent(
    title: str,
    content: str,
    publisher: str = "Market News",
    url: Optional[str] = None,
    published_at: Optional[str] = None,
) -> tuple[str, bool]:
    """
    Saves an article if not already present based on content_hash.
    Returns: (article_id, is_new)
    """
    run_migrations()
    now_iso = datetime.now(timezone.utc).isoformat()
    pub_iso = published_at or now_iso
    content_hash = compute_content_hash(f"{title} {content}")

    conn = get_db_connection()
    try:
        with conn:
            cur = conn.execute("SELECT id FROM news_articles WHERE content_hash = ?", (content_hash,))
            row = cur.fetchone()
            if row:
                return row["id"], False

            article_id = str(uuid.uuid4())[:12]
            conn.execute(
                """
                INSERT INTO news_articles (id, title, publisher, url, published_at, content, content_hash, ingestion_status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'ingested', ?)
                """,
                (article_id, title[:250], publisher[:100], url, pub_iso, content, content_hash, now_iso),
            )
            return article_id, True
    finally:
        conn.close()


def _safe_json_dumps(obj: Any) -> str:
    """Serializes objects to JSON safely, converting Pydantic models and Enums."""
    try:
        return json.dumps(obj, default=str)
    except Exception:
        try:
            if hasattr(obj, "model_dump"):
                return json.dumps(obj.model_dump(), default=str)
            elif hasattr(obj, "__dict__"):
                return json.dumps(obj.__dict__, default=str)
        except Exception:
            pass
        return json.dumps(str(obj))


def store_analysis_record(
    article_id: str,
    content_hash: str,
    model_version: str,
    is_relevant: bool,
    relevance_reason: str,
    sentiment: str,
    extracted_entities: list[Any],
    extracted_event: dict[str, Any],
    confidence: float,
    status: str = "completed",
    error_message: Optional[str] = None,
) -> str:
    """Stores or updates news analysis record."""
    run_migrations()
    now_iso = datetime.now(timezone.utc).isoformat()
    analysis_id = str(uuid.uuid4())[:12]

    conn = get_db_connection()
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO news_analyses (
                    id, article_id, content_hash, model_version, status,
                    is_relevant, relevance_reason, sentiment, extracted_entities,
                    extracted_event, confidence, error_message, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    analysis_id,
                    article_id,
                    content_hash,
                    model_version,
                    status,
                    1 if is_relevant else 0,
                    relevance_reason,
                    sentiment,
                    _safe_json_dumps(extracted_entities),
                    _safe_json_dumps(extracted_event),
                    confidence,
                    error_message,
                    now_iso,
                ),
            )
            return analysis_id
    finally:
        conn.close()


def persist_impact_and_knowledge_graph(
    article_id: str,
    analysis_id: str,
    event: Any,
    top_paths: Optional[list[Any]] = None,
    affected_assets: Optional[list[Any]] = None,
    response_edges: Optional[list[Any]] = None,
    response_nodes: Optional[list[Any]] = None,
    impact_edges: Optional[list[Any]] = None,
    impact_nodes: Optional[list[Any]] = None,
    news_text: str = "",
    publisher: str = "Market News",
    published_at: Optional[str] = None,
    demo_mode: bool = False,
    **kwargs: Any,
) -> dict[str, Any]:
    """
    Transactionally persists the Impact Graph and links it with Knowledge Graph tables.
    - Creates impact_events and impact_edges with hop distances and direct/indirect flags.
    - Attaches impact_evidence with verification status.
    - Merges new nodes/edges into cumulative kg_nodes and kg_edges.
    - Preserves conflicting claims and calculates confidence decay.
    """
    run_migrations()
    now_iso = datetime.now(timezone.utc).isoformat()
    pub_iso = published_at or now_iso
    event_id = str(uuid.uuid4())[:12]

    edges_list = response_edges if response_edges is not None else (impact_edges or [])
    nodes_list = response_nodes if response_nodes is not None else (impact_nodes or [])
    paths_list = top_paths or []

    primary_node = getattr(event, "primary_node", "unknown")
    event_type = getattr(event, "event_type", "Macro Shock")
    direction = getattr(event, "direction", "+")
    if hasattr(direction, "value"):
        direction = direction.value
    magnitude = getattr(event, "magnitude", None)
    shock_source = getattr(event, "shock_source", "unclear")
    evidence_sentence = getattr(event, "evidence_sentence", None) or (news_text[:200] if news_text else "")

    conn = get_db_connection()
    impact_edge_count = 0
    direct_edge_count = 0
    indirect_edge_count = 0

    try:
        with conn:
            # 1. Insert impact_event
            conn.execute(
                """
                INSERT INTO impact_events (
                    id, analysis_id, article_id, event_type, primary_node,
                    direction, magnitude, shock_source, evidence_sentence, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    analysis_id,
                    article_id,
                    event_type,
                    primary_node,
                    str(direction),
                    magnitude,
                    str(shock_source),
                    evidence_sentence,
                    now_iso,
                ),
            )

            # Determine hop distances from top paths
            node_hops: dict[str, int] = {primary_node: 0}
            for p in paths_list:
                p_nodes = getattr(p, "nodes", [])
                for idx, n in enumerate(p_nodes):
                    if n not in node_hops or idx < node_hops[n]:
                        node_hops[n] = idx

            # 2. Insert impact_edges
            for e in edges_list:
                src = getattr(e, "source", None) or e.get("source")
                tgt = getattr(e, "target", None) or e.get("target")
                if not src or not tgt or src.startswith("UNLINKED") or tgt.startswith("UNLINKED"):
                    continue

                sign_val = getattr(e, "sign", "+")
                if hasattr(sign_val, "value"):
                    sign_val = sign_val.value

                dir_val = "positive" if sign_val == "+" else ("negative" if sign_val == "-" else "mixed")
                is_direct = 1 if (src == primary_node or node_hops.get(src, 99) == 0) else 0
                hop_dist = node_hops.get(tgt, node_hops.get(src, 0) + 1)

                s_min = float(getattr(e, "strength_min", 0.4) or 0.4)
                s_max = float(getattr(e, "strength_max", 0.7) or 0.7)
                conf = float(getattr(e, "confidence", 0.5) or 0.5)
                # Confidence decay for indirect hops
                if hop_dist > 1:
                    conf = max(0.15, conf * (0.85 ** (hop_dist - 1)))

                time_h = getattr(e, "time_horizon", "short")
                expl = getattr(e, "reasoning", "") or f"Causal transmission channel from {src} to {tgt}."
                ev_text = getattr(e, "evidence", "") or evidence_sentence

                edge_record_id = f"{event_id}:{src}->{tgt}"
                conn.execute(
                    """
                    INSERT OR REPLACE INTO impact_edges (
                        id, event_id, source, target, direction, category,
                        is_direct, hop_distance, strength_min, strength_max,
                        confidence, time_horizon, explanation, evidence_text, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        edge_record_id,
                        event_id,
                        src,
                        tgt,
                        dir_val,
                        "direct" if is_direct else "indirect",
                        is_direct,
                        hop_dist,
                        s_min,
                        s_max,
                        round(conf, 3),
                        time_h,
                        expl,
                        ev_text,
                        now_iso,
                    ),
                )
                impact_edge_count += 1
                if is_direct:
                    direct_edge_count += 1
                else:
                    indirect_edge_count += 1

                # 3. Insert impact_evidence
                v_status = "verified_news_fact" if is_direct else "established_mechanism"
                ev_id = str(uuid.uuid4())[:12]
                conn.execute(
                    """
                    INSERT INTO impact_evidence (
                        id, edge_id, article_id, quote, source, published_at, verification_status, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        ev_id,
                        edge_record_id,
                        article_id,
                        ev_text[:300],
                        publisher,
                        pub_iso,
                        v_status,
                        now_iso,
                    ),
                )

        logger.info(
            "Persisted Impact Graph event %s with %d edges (%d direct, %d indirect)",
            event_id, impact_edge_count, direct_edge_count, indirect_edge_count
        )

        # 4. Integrate into Knowledge Graph store
        from app.knowledge_graph import merge_analysis_into_kg
        kg_result = merge_analysis_into_kg(
            event=event,
            response_nodes=nodes_list,
            response_edges=edges_list,
            news_text=news_text,
            source=publisher,
            published_at=pub_iso,
        )

        return {
            "event_id": event_id,
            "article_id": article_id,
            "analysis_id": analysis_id,
            "impact_edges_count": impact_edge_count,
            "direct_edges": direct_edge_count,
            "indirect_edges": indirect_edge_count,
            "kg_update": kg_result,
        }
    finally:
        conn.close()


# ── Query Functions for APIs ──────────────────────────────────────────────────

def get_persisted_impact_graph(event_id: Optional[str] = None) -> dict[str, Any]:
    """
    Returns Impact Graph nodes and edges directly from SQLite persistence.
    If event_id is None, returns the most recent impact event.
    """
    run_migrations()
    conn = get_db_connection()
    try:
        if event_id:
            cur_ev = conn.execute("SELECT * FROM impact_events WHERE id = ?", (event_id,))
        else:
            cur_ev = conn.execute("SELECT * FROM impact_events ORDER BY timestamp DESC LIMIT 1")

        ev_row = cur_ev.fetchone()
        if not ev_row:
            return {"event": None, "nodes": [], "edges": [], "stats": {"total_nodes": 0, "total_edges": 0}}

        event_dict = dict(ev_row)
        ev_id = event_dict["id"]

        # Fetch edges
        cur_edges = conn.execute(
            """
            SELECT e.*, ev.quote as evidence_quote, ev.verification_status, ev.source as evidence_source
            FROM impact_edges e
            LEFT JOIN impact_evidence ev ON e.id = ev.edge_id
            WHERE e.event_id = ?
            ORDER BY e.hop_distance ASC, e.confidence DESC
            """,
            (ev_id,),
        )
        edge_rows = cur_edges.fetchall()

        edges = []
        node_ids = set()
        for r in edge_rows:
            d = dict(r)
            node_ids.add(d["source"])
            node_ids.add(d["target"])
            edges.append({
                "id": d["id"],
                "source": d["source"],
                "target": d["target"],
                "direction": d["direction"],
                "category": d["category"],
                "is_direct": bool(d["is_direct"]),
                "hop_distance": d["hop_distance"],
                "strength_min": d["strength_min"],
                "strength_max": d["strength_max"],
                "confidence": d["confidence"],
                "time_horizon": d["time_horizon"],
                "explanation": d["explanation"],
                "evidence": d["evidence_text"] or d["evidence_quote"],
                "verification_status": d["verification_status"] or "established_mechanism",
                "evidence_source": d["evidence_source"] or "Market News",
            })

        # Fetch nodes from kg_nodes
        nodes = []
        if node_ids:
            placeholders = ",".join(["?"] * len(node_ids))
            cur_nodes = conn.execute(
                f"SELECT * FROM kg_nodes WHERE id IN ({placeholders})",
                list(node_ids),
            )
            nodes = [dict(r) for r in cur_nodes.fetchall()]

        return {
            "event": event_dict,
            "nodes": nodes,
            "edges": edges,
            "stats": {
                "total_nodes": len(nodes),
                "total_edges": len(edges),
                "direct_edges": sum(1 for e in edges if e["is_direct"]),
                "indirect_edges": sum(1 for e in edges if not e["is_direct"]),
            },
        }
    finally:
        conn.close()


def get_entity_profile(entity_id: str) -> Optional[dict[str, Any]]:
    """Retrieves entity metadata, mention counts, and connected edges from SQLite."""
    run_migrations()
    conn = get_db_connection()
    try:
        clean_id = entity_id.strip()
        cur = conn.execute(
            """
            SELECT * FROM kg_nodes
            WHERE id = ? OR LOWER(id) = LOWER(?) OR LOWER(label) = LOWER(?) OR LOWER(label) LIKE LOWER(?)
            ORDER BY CASE WHEN id = ? THEN 1 WHEN LOWER(id) = LOWER(?) THEN 2 ELSE 3 END
            LIMIT 1
            """,
            (clean_id, clean_id, clean_id, f"%{clean_id}%", clean_id, clean_id),
        )
        node_row = cur.fetchone()
        if not node_row:
            return None

        node_data = dict(node_row)
        matched_id = node_data["id"]

        # Incoming & outgoing edges in KG
        cur_out = conn.execute("SELECT * FROM kg_edges WHERE source = ?", (matched_id,))
        out_edges = [dict(r) for r in cur_out.fetchall()]

        cur_in = conn.execute("SELECT * FROM kg_edges WHERE target = ?", (matched_id,))
        in_edges = [dict(r) for r in cur_in.fetchall()]

        # Recent impact events referencing this entity
        cur_ev = conn.execute(
            """
            SELECT ie.event_type, ie.direction, ie.timestamp, e.explanation, e.confidence, e.is_direct
            FROM impact_edges e
            JOIN impact_events ie ON e.event_id = ie.id
            WHERE e.source = ? OR e.target = ?
            ORDER BY ie.timestamp DESC LIMIT 10
            """,
            (matched_id, matched_id),
        )
        recent_impacts = [dict(r) for r in cur_ev.fetchall()]

        return {
            "entity": node_data,
            "outgoing_edges": out_edges,
            "incoming_edges": in_edges,
            "recent_impacts": recent_impacts,
        }
    finally:
        conn.close()


def get_edge_evidence_details(edge_id: str) -> Optional[dict[str, Any]]:
    """Retrieves full provenance, conflict notes, and evidence list for an edge."""
    run_migrations()
    conn = get_db_connection()
    try:
        src_part = edge_id.split("->")[0].split(">")[0].strip() if ("->" in edge_id or ">" in edge_id) else ""
        tgt_part = edge_id.split("->")[1].strip() if "->" in edge_id else (edge_id.split(">")[1].strip() if ">" in edge_id else "")

        # Check impact_edges first
        cur_imp = conn.execute(
            """
            SELECT e.*, ie.event_type, ie.primary_node as event_trigger, a.title as article_title, a.url as article_url, a.publisher
            FROM impact_edges e
            JOIN impact_events ie ON e.event_id = ie.id
            LEFT JOIN news_articles a ON ie.article_id = a.id
            WHERE e.id = ? OR e.id LIKE ? OR (LOWER(e.source) = LOWER(?) AND LOWER(e.target) = LOWER(?))
            ORDER BY e.created_at DESC LIMIT 1
            """,
            (edge_id, f"%:{edge_id}", src_part, tgt_part),
        )
        row = cur_imp.fetchone()
        if row:
            d = dict(row)
            actual_id = d["id"]
            # Fetch evidence items
            cur_ev = conn.execute("SELECT * FROM impact_evidence WHERE edge_id = ?", (actual_id,))
            evidence_items = [dict(r) for r in cur_ev.fetchall()]
            d["evidence_items"] = evidence_items
            return d

        # Check kg_edges
        cur_kg = conn.execute("SELECT * FROM kg_edges WHERE id = ?", (edge_id,))
        kg_row = cur_kg.fetchone()
        if kg_row:
            d = dict(kg_row)
            try:
                d["evidence_list"] = json.loads(d.get("evidence_list") or "[]")
            except Exception:
                d["evidence_list"] = []
            return d

        return None
    finally:
        conn.close()


def get_all_persisted_articles(limit: int = 25) -> list[dict[str, Any]]:
    """Returns list of ingested articles and their analysis status."""
    run_migrations()
    conn = get_db_connection()
    try:
        cur = conn.execute(
            """
            SELECT a.id, a.title, a.publisher, a.url, a.published_at, a.ingestion_status, a.created_at,
                   na.status as analysis_status, na.sentiment, na.is_relevant, na.relevance_reason
            FROM news_articles a
            LEFT JOIN news_analyses na ON a.id = na.article_id
            ORDER BY a.published_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()
