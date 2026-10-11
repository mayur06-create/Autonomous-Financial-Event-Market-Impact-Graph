"""Knowledge Base: SQLite graph storage with schema migration, seed loading,
incremental edge upsert (support counts, EMAs, conflict resolution),
time decay, and MiniLM embedding-based article retrieval.
"""
import json
import math
import os
import re
import sqlite3
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import networkx as nx
import numpy as np

from . import config

SCHEMA_V2 = """
CREATE TABLE IF NOT EXISTS articles(
  id TEXT PRIMARY KEY,
  title TEXT,
  description TEXT,
  url TEXT,
  source TEXT,
  published_at TEXT,
  sentiment REAL,
  primary_event TEXT,
  features_json TEXT,
  summary TEXT,
  engine TEXT,
  ingested_at TEXT,
  embedding BLOB
);

CREATE TABLE IF NOT EXISTS nodes(
  id TEXT PRIMARY KEY,
  label TEXT,
  type TEXT,
  aliases_json TEXT,
  ticker TEXT,
  embedding BLOB,
  first_seen TEXT,
  last_seen TEXT,
  mention_count INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS edges(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_id TEXT,
  target_id TEXT,
  relation TEXT,
  sign INTEGER DEFAULT 1,
  strength REAL DEFAULT 0.5,
  confidence REAL DEFAULT 0.5,
  kind TEXT DEFAULT 'knowledge',
  reason TEXT,
  evidence_text TEXT,
  article_ids_json TEXT,
  support_count INTEGER DEFAULT 1,
  first_seen TEXT,
  last_seen TEXT,
  conflict INTEGER DEFAULT 0,
  article_id TEXT,
  effect TEXT,
  impact TEXT,
  created_at TEXT
);

CREATE TABLE IF NOT EXISTS sector_impacts(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  article_id TEXT,
  sector TEXT,
  score REAL,
  horizon TEXT,
  confidence REAL,
  explanation TEXT,
  published_at TEXT
);

CREATE TABLE IF NOT EXISTS revisions(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  article_id TEXT,
  prior_article_id TEXT,
  family TEXT,
  deltas_json TEXT,
  pros_json TEXT,
  cons_json TEXT,
  net_effect TEXT,
  explanation TEXT,
  engine TEXT,
  similarity REAL DEFAULT 0.0,
  created_at TEXT
);

CREATE TABLE IF NOT EXISTS news_inbox(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  uuid TEXT UNIQUE,
  title TEXT,
  description TEXT,
  url TEXT UNIQUE,
  source TEXT,
  published_at TEXT,
  image_url TEXT,
  entities_json TEXT,
  sentiment_marketaux REAL,
  fetched_at TEXT,
  status TEXT DEFAULT 'new',
  search_query TEXT
);

CREATE INDEX IF NOT EXISTS ix_edges_source ON edges(source_id);
CREATE INDEX IF NOT EXISTS ix_edges_target ON edges(target_id);
CREATE INDEX IF NOT EXISTS ix_edges_rel ON edges(source_id, target_id, relation);
CREATE INDEX IF NOT EXISTS ix_si_article ON sector_impacts(article_id);
CREATE INDEX IF NOT EXISTS ix_si_sector ON sector_impacts(sector, published_at);
CREATE INDEX IF NOT EXISTS ix_art_pub ON articles(published_at);
CREATE INDEX IF NOT EXISTS ix_inbox_uuid ON news_inbox(uuid);
CREATE INDEX IF NOT EXISTS ix_inbox_status ON news_inbox(status);
"""


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "x"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class KnowledgeBase:
    def __init__(self, path: Optional[str] = None):
        self.path = str(path or config.db_path())
        if self.path != ":memory:":
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA_V2)
        self._migrate()
        self._seed_priors()

    # ------------------------------------------------------------ migration
    def _migrate(self):
        """Add any missing columns to older schema tables."""
        with self.lock, self.db:
            # Nodes columns
            cols = {r["name"] for r in self.db.execute("PRAGMA table_info(nodes)").fetchall()}
            for col, col_def in [
                ("aliases_json", "TEXT"),
                ("ticker", "TEXT"),
                ("embedding", "BLOB"),
                ("first_seen", "TEXT"),
                ("last_seen", "TEXT"),
                ("mention_count", "INTEGER DEFAULT 1"),
            ]:
                if col not in cols:
                    try:
                        self.db.execute(f"ALTER TABLE nodes ADD COLUMN {col} {col_def}")
                    except Exception:
                        pass

            # Edges columns
            cols = {r["name"] for r in self.db.execute("PRAGMA table_info(edges)").fetchall()}
            for col, col_def in [
                ("sign", "INTEGER DEFAULT 1"),
                ("confidence", "REAL DEFAULT 0.5"),
                ("evidence_text", "TEXT"),
                ("article_ids_json", "TEXT"),
                ("support_count", "INTEGER DEFAULT 1"),
                ("first_seen", "TEXT"),
                ("last_seen", "TEXT"),
                ("conflict", "INTEGER DEFAULT 0"),
            ]:
                if col not in cols:
                    try:
                        self.db.execute(f"ALTER TABLE edges ADD COLUMN {col} {col_def}")
                    except Exception:
                        pass

            # Articles columns
            cols = {r["name"] for r in self.db.execute("PRAGMA table_info(articles)").fetchall()}
            if "embedding" not in cols:
                try:
                    self.db.execute("ALTER TABLE articles ADD COLUMN embedding BLOB")
                except Exception:
                    pass

            # is_demo column on articles and sector_impacts
            for tbl in ("articles", "sector_impacts"):
                tcols = {r["name"] for r in self.db.execute(f"PRAGMA table_info({tbl})").fetchall()}
                if "is_demo" not in tcols:
                    try:
                        self.db.execute(f"ALTER TABLE {tbl} ADD COLUMN is_demo INTEGER DEFAULT 0")
                    except Exception:
                        pass

            try:
                self.db.execute("UPDATE articles SET is_demo=1 WHERE published_at IN ('2022-02-24', '2024-01-01') OR id LIKE 'demo-%'")
                self.db.execute("UPDATE sector_impacts SET is_demo=1 WHERE published_at IN ('2022-02-24', '2024-01-01') OR article_id LIKE 'demo-%'")
            except Exception:
                pass

            # Revisions columns
            cols = {r["name"] for r in self.db.execute("PRAGMA table_info(revisions)").fetchall()}
            if "similarity" not in cols:
                try:
                    self.db.execute("ALTER TABLE revisions ADD COLUMN similarity REAL DEFAULT 0.0")
                except Exception:
                    pass

            # news_inbox — create if migrating from older DB
            self.db.executescript("""
            CREATE TABLE IF NOT EXISTS news_inbox(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              uuid TEXT UNIQUE,
              title TEXT,
              description TEXT,
              url TEXT UNIQUE,
              source TEXT,
              published_at TEXT,
              image_url TEXT,
              entities_json TEXT,
              sentiment_marketaux REAL,
              fetched_at TEXT,
              status TEXT DEFAULT 'new',
              search_query TEXT
            );
            CREATE INDEX IF NOT EXISTS ix_inbox_uuid ON news_inbox(uuid);
            CREATE INDEX IF NOT EXISTS ix_inbox_status ON news_inbox(status);
            """)

    # ------------------------------------------------------------ seeding
    def _seed_priors(self):
        """Seed graph with curated domain knowledge from data/seed_kb.json."""
        seed_file = Path(__file__).resolve().parent.parent / "data" / "seed_kb.json"
        if not seed_file.exists():
            return
        try:
            data = json.loads(seed_file.read_text(encoding="utf-8"))
        except Exception:
            return

        with self.lock, self.db:
            for n in data.get("nodes", []):
                nid = n["id"]
                aliases = json.dumps(n.get("aliases", []))
                ticker = n.get("ticker")
                ntype = n.get("type", "Sector")
                now = _now()
                self.db.execute(
                    """INSERT OR IGNORE INTO nodes(id, label, type, aliases_json, ticker, first_seen, last_seen, mention_count)
                       VALUES(?, ?, ?, ?, ?, ?, ?, 1)""",
                    (nid, nid, ntype, aliases, ticker, now, now),
                )

            for e in data.get("edges", []):
                src, tgt = e["source"], e["target"]
                sign = int(e.get("sign", 1))
                strength = float(e.get("strength", 0.7))
                reason = e.get("reason", "Domain economic relationship")
                now = _now()
                # Check if knowledge edge already exists
                row = self.db.execute(
                    "SELECT id FROM edges WHERE source_id=? AND target_id=? AND kind='knowledge'",
                    (src, tgt),
                ).fetchone()
                if not row:
                    self.db.execute(
                        """INSERT INTO edges(source_id, target_id, relation, sign, strength, confidence,
                                             kind, reason, evidence_text, article_ids_json, support_count,
                                             first_seen, last_seen, conflict, effect, created_at)
                           VALUES(?, ?, ?, ?, ?, ?, 'knowledge', ?, 'Curated domain knowledge prior',
                                  '[]', 1, ?, ?, 0, ?, ?)""",
                        (
                            src,
                            tgt,
                            "affects",
                            sign,
                            strength,
                            strength,
                            reason,
                            now,
                            now,
                            "positive" if sign > 0 else "negative",
                            now,
                        ),
                    )

    # ------------------------------------------------------------ helpers
    def _all(self, sql: str, args: tuple = ()) -> List[dict]:
        with self.lock:
            return [dict(r) for r in self.db.execute(sql, args).fetchall()]

    def _one(self, sql: str, args: tuple = ()) -> Optional[dict]:
        rows = self._all(sql, args)
        return rows[0] if rows else None

    # ------------------------------------------------------------ node ops
    def upsert_node(
        self,
        node_id: str,
        label: str,
        node_type: str,
        aliases: Optional[List[str]] = None,
        ticker: Optional[str] = None,
        embedding: Optional[bytes] = None,
    ) -> str:
        """Upsert a node: increment mention count and update last_seen."""
        now = _now()
        with self.lock, self.db:
            existing = self._one("SELECT * FROM nodes WHERE id=?", (node_id,))
            if existing:
                cur_aliases = json.loads(existing.get("aliases_json") or "[]")
                if aliases:
                    cur_aliases = list(set(cur_aliases + aliases))
                t = ticker or existing.get("ticker")
                self.db.execute(
                    """UPDATE nodes SET mention_count = mention_count + 1, last_seen=?,
                                        aliases_json=?, ticker=COALESCE(?, ticker) WHERE id=?""",
                    (now, json.dumps(cur_aliases), t, node_id),
                )
                return node_id
            else:
                self.db.execute(
                    """INSERT INTO nodes(id, label, type, aliases_json, ticker, embedding, first_seen, last_seen, mention_count)
                       VALUES(?, ?, ?, ?, ?, ?, ?, ?, 1)""",
                    (node_id, label, node_type, json.dumps(aliases or []), ticker, embedding, now, now),
                )
                return node_id

    # ------------------------------------------------------------ edge ops
    def upsert_edge(
        self,
        source_id: str,
        target_id: str,
        relation: str,
        sign: int,
        strength: float,
        confidence: float,
        kind: str,
        reason: str,
        evidence_text: str,
        article_id: Optional[str] = None,
        event_date: Optional[str] = None,
    ) -> int:
        """Incremental edge update:
        - Same sign: support_count++, EMA on strength, update last_seen.
        - Opposite sign: set conflict=1 and retain both.
        """
        now = event_date or _now()
        with self.lock, self.db:
            # Look for existing edges between source and target
            existing = self._all(
                "SELECT * FROM edges WHERE source_id=? AND target_id=? AND relation=?",
                (source_id, target_id, relation),
            )
            opposite_edges = self._all(
                "SELECT * FROM edges WHERE source_id=? AND target_id=? AND sign!=?",
                (source_id, target_id, sign),
            )
            has_opposite = len(opposite_edges) > 0
            matched = existing[0] if existing else None

            if matched:
                edge_id = matched["id"]
                sup = (matched.get("support_count") or 1) + 1
                old_str = matched.get("strength") or strength
                # EMA: 70% old, 30% new
                new_str = round(0.7 * old_str + 0.3 * strength, 3)
                old_conf = matched.get("confidence") or confidence
                new_conf = round(min(1.0, max(old_conf, confidence) * 1.05), 3)

                art_ids = json.loads(matched.get("article_ids_json") or "[]")
                if article_id and article_id not in art_ids:
                    art_ids.append(article_id)

                self.db.execute(
                    """UPDATE edges SET support_count=?, strength=?, confidence=?, last_seen=?,
                                        article_ids_json=?, reason=COALESCE(NULLIF(?, ''), reason),
                                        evidence_text=COALESCE(NULLIF(?, ''), evidence_text)
                       WHERE id=?""",
                    (sup, new_str, new_conf, now, json.dumps(art_ids), reason, evidence_text, edge_id),
                )
                return edge_id
            else:
                art_ids = [article_id] if article_id else []
                conflict_flag = 1 if has_opposite else 0
                if has_opposite:
                    self.db.execute(
                        "UPDATE edges SET conflict=1 WHERE source_id=? AND target_id=?",
                        (source_id, target_id),
                    )

                cur = self.db.execute(
                    """INSERT INTO edges(source_id, target_id, relation, sign, strength, confidence,
                                         kind, reason, evidence_text, article_ids_json, support_count,
                                         first_seen, last_seen, conflict, article_id, effect, created_at)
                       VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?)""",
                    (
                        source_id,
                        target_id,
                        relation,
                        sign,
                        strength,
                        confidence,
                        kind,
                        reason,
                        evidence_text,
                        json.dumps(art_ids),
                        now,
                        now,
                        conflict_flag,
                        article_id,
                        "positive" if sign > 0 else "negative",
                        now,
                    ),
                )
                return cur.lastrowid

    # ------------------------------------------------------------ time decay
    def calculate_decay(self, edge: dict, as_of_date: Optional[str] = None) -> float:
        """Compute time decay for edge confidence.
        Knowledge edges: factor 1.0 (never decay).
        Observed edges: factor 1.0.
        Inferred edges: decay * exp(-days / tau).
        """
        kind = edge.get("kind", "knowledge")
        conf = float(edge.get("confidence", 0.5))
        if kind in ("knowledge", "observed"):
            return conf

        tau = float(os.getenv("NEWSGRAPH_DECAY_TAU", "30.0"))
        last_str = edge.get("last_seen") or edge.get("created_at") or _now()
        ref_str = as_of_date or _now()
        try:
            d_last = datetime.fromisoformat(last_str[:19])
            d_ref = datetime.fromisoformat(ref_str[:19])
            days = max(0.0, (d_ref - d_last).total_seconds() / 86400.0)
        except Exception:
            days = 0.0

        decay_factor = math.exp(-days / max(1.0, tau))
        return round(conf * decay_factor, 3)

    # ------------------------------------------------------------ article persistence
    def has_article(self, aid: str) -> bool:
        return self._one("SELECT 1 AS x FROM articles WHERE id=?", (aid,)) is not None

    def delete_article(self, aid: str):
        with self.lock, self.db:
            for t in ("edges", "sector_impacts"):
                self.db.execute(f"DELETE FROM {t} WHERE article_id=?", (aid,))
            self.db.execute("DELETE FROM revisions WHERE article_id=?", (aid,))
            self.db.execute("DELETE FROM nodes WHERE id=?", (f"event:{aid}",))
            self.db.execute("DELETE FROM articles WHERE id=?", (aid,))

    def save_analysis(self, art, feats: dict, analysis: dict, embedding: Optional[bytes] = None):
        evid = f"event:{art.uuid}"
        now = _now()
        is_demo_val = 1 if (
            str(art.published_at).startswith("2022-02-24") or
            str(art.published_at).startswith("2024-01-01") or
            str(getattr(art, "uuid", "")).startswith("demo-")
        ) else 0

        with self.lock, self.db:
            # Clean previous article records to avoid duplicate edges upon re-analysis
            self.db.execute("DELETE FROM edges WHERE article_id=?", (art.uuid,))
            self.db.execute("DELETE FROM sector_impacts WHERE article_id=?", (art.uuid,))
            self.db.execute("DELETE FROM revisions WHERE article_id=?", (art.uuid,))

            # 1. Save Article
            self.db.execute(
                """INSERT OR REPLACE INTO articles(id, title, description, url, source, published_at,
                                                   sentiment, primary_event, features_json, summary,
                                                   engine, ingested_at, embedding, is_demo)
                   VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    art.uuid,
                    art.title,
                    art.description,
                    art.url,
                    art.source,
                    art.published_at,
                    feats.get("sentiment", {}).get("score", 0.0),
                    feats.get("primary_event"),
                    json.dumps(feats),
                    analysis.get("summary", ""),
                    analysis.get("engine", "heuristic"),
                    now,
                    embedding,
                    is_demo_val,
                ),
            )

            # 2. Save Event Node
            ev_label = art.title[:80]
            self.upsert_node(evid, ev_label, "Event")

            # 3. OBSERVED edges: Event -> linked entities
            for ent in feats.get("entities", []):
                ent_id = ent.get("linked_node_id") or ent.get("name")
                if not ent_id or ent_id == evid:
                    continue
                ent_type = ent.get("node_type") or ent.get("type", "Company")
                self.upsert_node(ent_id, ent.get("name", ent_id), ent_type, ticker=ent.get("ticker"))

                # Evidence sentence
                ev_sent = art.title
                if "sentiment" in feats and "sentences" in feats["sentiment"]:
                    sents = feats["sentiment"]["sentences"]
                    for s in sents:
                        if ent_id.lower() in s["sentence"].lower():
                            ev_sent = s["sentence"]
                            break

                ent_sent = ent.get("sentiment") or 0.0
                sign = 1 if ent_sent >= 0 else -1
                link_score = float(ent.get("link_score", 1.0))

                self.upsert_edge(
                    source_id=evid,
                    target_id=ent_id,
                    relation="mentions",
                    sign=sign,
                    strength=round(max(0.4, link_score), 2),
                    confidence=round(link_score, 2),
                    kind="observed",
                    reason=f"Observed in article text with {link_score*100:.0f}% linking confidence.",
                    evidence_text=ev_sent,
                    article_id=art.uuid,
                    event_date=art.published_at,
                )

            # 4. INFERRED edges from Gemini/fallback
            for r in analysis.get("relations", []):
                s, t = r["source"], r["target"]
                st, tt = r.get("source_type", "Company"), r.get("target_type", "Sector")
                self.upsert_node(s, s, st)
                self.upsert_node(t, t, tt)

                eff = r.get("effect", "positive")
                sign = 1 if eff == "positive" else -1 if eff == "negative" else 0
                strength = float(r.get("strength", 0.5))

                self.upsert_edge(
                    source_id=s,
                    target_id=t,
                    relation=r.get("relation", "affects"),
                    sign=sign if sign != 0 else 1,
                    strength=strength,
                    confidence=strength,
                    kind="inferred",
                    reason=r.get("reason", "Inferred relationship"),
                    evidence_text=r.get("impact", art.title),
                    article_id=art.uuid,
                    event_date=art.published_at,
                )

            # 5. Connect Event to trigger node
            primary_ev = feats.get("primary_event_meta")
            if primary_ev and primary_ev.get("trigger_node"):
                trig = primary_ev["trigger_node"]
                trig_sign = primary_ev.get("sign", 1)
                self.upsert_node(trig, trig, "Indicator")
                self.upsert_edge(
                    source_id=evid,
                    target_id=trig,
                    relation="triggers",
                    sign=trig_sign,
                    strength=0.95,
                    confidence=0.95,
                    kind="observed",
                    reason=f"Primary detected event: {primary_ev.get('label')}",
                    evidence_text=art.title,
                    article_id=art.uuid,
                    event_date=art.published_at,
                )

            # 6. Sector Impacts
            for i in analysis.get("sector_impacts", []):
                self.db.execute(
                    """INSERT INTO sector_impacts(article_id, sector, score, horizon, confidence, explanation, published_at, is_demo)
                       VALUES(?, ?, ?, ?, ?, ?, ?, ?)""",
                    (art.uuid, i["sector"], i["score"], i["horizon"], i["confidence"], i["explanation"], art.published_at, is_demo_val),
                )
                self.upsert_node(i["sector"], i["sector"], "Sector")
                eff = "positive" if i["score"] > 0.1 else "negative" if i["score"] < -0.1 else "neutral"
                self.upsert_edge(
                    source_id=evid,
                    target_id=i["sector"],
                    relation="impacts",
                    sign=1 if i["score"] >= 0 else -1,
                    strength=round(abs(i["score"]), 2),
                    confidence=round(i.get("confidence", 0.6), 2),
                    kind="inferred",
                    reason=i.get("explanation", ""),
                    evidence_text=art.title,
                    article_id=art.uuid,
                    event_date=art.published_at,
                )

    def save_revision(self, rev: dict):
        with self.lock, self.db:
            self.db.execute(
                """INSERT INTO revisions(article_id, prior_article_id, family, deltas_json, pros_json, cons_json,
                                         net_effect, explanation, engine, similarity, created_at)
                   VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    rev["article_id"],
                    rev["prior_article_id"],
                    rev.get("family", ""),
                    json.dumps(rev["deltas"]),
                    json.dumps(rev["pros"]),
                    json.dumps(rev["cons"]),
                    rev["net_effect"],
                    rev["explanation"],
                    rev["engine"],
                    float(rev.get("similarity", 0.0)),
                    _now(),
                ),
            )
            rel = "reverses earlier impact" if rev.get("reversed") else "follows up on"
            self.upsert_edge(
                source_id=f"event:{rev['article_id']}",
                target_id=f"event:{rev['prior_article_id']}",
                relation=rel,
                sign=1 if rev.get("net_effect") == "positive" else -1,
                strength=min(1.0, abs(rev.get("net_delta", 0.5)) / 2),
                confidence=float(rev.get("similarity", 0.7)),
                kind="inferred",
                reason=rev.get("explanation", ""),
                evidence_text=" | ".join((rev.get("pros", [])[:2] + rev.get("cons", [])[:2])),
                article_id=rev["article_id"],
            )

    def reset(self):
        with self.lock, self.db:
            for t in ("edges", "nodes", "sector_impacts", "revisions", "articles"):
                self.db.execute(f"DELETE FROM {t}")
        self._seed_priors()

    # ------------------------------------------------------------ retrieval
    def sector_scores(self, aid: str) -> dict:
        return {
            r["sector"]: r["score"]
            for r in self._all("SELECT sector,score FROM sector_impacts WHERE article_id=?", (aid,))
        }

    def find_related(self, embedding: bytes, before: str, exclude_id: Optional[str] = None, limit: int = 3) -> List[dict]:
        """Find earlier articles via MiniLM embedding cosine similarity (replaces family matching)."""
        from .nlp.retrieval import find_similar_articles

        rows = self._all(
            """SELECT id, title, published_at, summary, embedding FROM articles
               WHERE published_at < ? AND id != ? AND embedding IS NOT NULL
               ORDER BY published_at DESC""",
            (before, exclude_id or ""),
        )
        candidates = []
        for r in rows:
            candidates.append({
                "id": r["id"],
                "title": r["title"],
                "published_at": r["published_at"],
                "summary": r["summary"],
                "embedding": r["embedding"],
                "scores": self.sector_scores(r["id"]),
            })

        if not embedding or not candidates:
            return []

        query_vec = np.frombuffer(embedding, dtype=np.float32)
        return find_similar_articles(query_vec, candidates, top_k=limit)

    # ------------------------------------------------------------ query views
    def articles(self) -> List[dict]:
        rows = self._all(
            """SELECT id, title, url, source, published_at, sentiment, primary_event, features_json, summary, engine
               FROM articles ORDER BY published_at DESC"""
        )
        for r in rows:
            f = json.loads(r.pop("features_json") or "{}")
            r["events"] = [e.get("label", e.get("type", "")) for e in f.get("events", [])]
            r["keywords"] = [k["keyword"] for k in f.get("keywords", [])[:5]]
        return rows

    def article(self, aid: str) -> Optional[dict]:
        a = self._one("SELECT * FROM articles WHERE id=?", (aid,))
        if not a:
            return None
        f = json.loads(a.pop("features_json") or "{}")
        a.pop("embedding", None)
        a["features"] = {
            k: f.get(k)
            for k in ("keywords", "bigrams", "entities", "sectors", "events", "numbers", "sentiment", "n_tokens")
        }
        a["tokens_preview"] = f.get("tokens", [])[:40]
        a["sector_impacts"] = self._all(
            """SELECT sector, score, horizon, confidence, explanation FROM sector_impacts
               WHERE article_id=? ORDER BY ABS(score) DESC""",
            (aid,),
        )
        a["revisions"] = self.revisions(article_id=aid)
        return a

    def generate_edge_sentence(self, edge: dict) -> str:
        """Generate a plain-English explanation sentence from edge data."""
        src = edge.get("from") or edge.get("source_id", "")
        tgt = edge.get("to") or edge.get("target_id", "")
        sign = int(edge.get("sign", 1))
        conf = int(float(edge.get("confidence", 0.5)) * 100)
        strength = round(float(edge.get("strength", 0.5)), 2)
        reason = edge.get("reason") or ""
        kind = edge.get("kind", "knowledge")

        verb = "tends to rise" if sign > 0 else "tends to fall"
        source_label = {
            "knowledge": "knowledge-base economic prior",
            "observed": "observed article reporting",
            "inferred": "inferred relationship",
        }.get(kind, kind)

        sent = f"When {src} rises, {tgt} {verb} (strength {strength}, confidence {conf}%)."
        if reason:
            sent += f" Why: {reason}."
        sent += f" Source: {source_label}."
        return sent

    def get_edge_details(self, edge_id: str) -> Optional[dict]:
        """Return rich edge metadata, plain English explanation, and supporting evidence."""
        eid_str = str(edge_id)
        if eid_str.startswith("bundle-"):
            parts = eid_str[len("bundle-"):].split("-", 1)
            if len(parts) == 2:
                src, tgt = parts
                edges = self._all("SELECT * FROM edges WHERE source_id=? AND target_id=?", (src, tgt))
            else:
                edges = []
        else:
            try:
                edges = self._all("SELECT * FROM edges WHERE id=?", (int(edge_id),))
            except Exception:
                edges = self._all("SELECT * FROM edges WHERE id=?", (edge_id,))

        if not edges:
            return None

        primary = edges[0]
        all_aids = set()
        for e in edges:
            if e.get("article_id"):
                all_aids.add(e["article_id"])
            for aid in json.loads(e.get("article_ids_json") or "[]"):
                all_aids.add(aid)

        arts = []
        if all_aids:
            placeholders = ",".join("?" for _ in all_aids)
            arts = self._all(
                f"SELECT id, title, published_at, sentiment FROM articles WHERE id IN ({placeholders}) ORDER BY published_at DESC",
                tuple(all_aids),
            )

        signs = {e["sign"] for e in edges}
        conflict_msg = (
            "Conflict detected: opposing directional claims observed between these nodes across articles."
            if len(signs) > 1 else None
        )

        return {
            "id": edge_id,
            "edge": primary,
            "all_edges": edges,
            "bundle_count": len(edges),
            "plain_english": self.generate_edge_sentence(primary),
            "reason": primary.get("reason"),
            "evidence_text": primary.get("evidence_text") or primary.get("reason"),
            "supporting_articles": arts,
            "conflict": len(signs) > 1 or bool(primary.get("conflict")),
            "conflict_explanation": conflict_msg,
        }

    def get_node_details(self, node_id: str) -> Optional[dict]:
        """Return rich node details, role, importance, connected edges, and price data."""
        node = self._one("SELECT * FROM nodes WHERE id=?", (node_id,))
        if not node:
            return None
        node = dict(node)
        node["aliases"] = json.loads(node.get("aliases_json") or "[]")
        node.pop("embedding", None)

        incoming = self._all(
            "SELECT e.*, e.source_id AS 'from', e.target_id AS 'to' FROM edges e WHERE target_id=?",
            (node_id,)
        )
        outgoing = self._all(
            "SELECT e.*, e.source_id AS 'from', e.target_id AS 'to' FROM edges e WHERE source_id=?",
            (node_id,)
        )

        articles = self._all(
            """SELECT a.id, a.title, a.published_at, a.sentiment FROM articles a
               JOIN edges e ON (e.article_id=a.id OR e.article_ids_json LIKE ('%' || a.id || '%'))
               WHERE e.source_id=? OR e.target_id=? GROUP BY a.id ORDER BY a.published_at DESC LIMIT 8""",
            (node_id, node_id),
        )

        ntype = node.get("type", "Company")
        if ntype == "Event":
            role = "Event"
        elif ntype == "Sector":
            role = "Sector"
        elif len(incoming) == 0 and len(outgoing) > 0:
            role = "Trigger/Driver"
        elif len(incoming) > 0 and len(outgoing) == 0:
            role = "Receiver/Asset"
        else:
            role = "Transmitter"

        summary = (
            f"{node_id} functions as a {role} ({ntype}). It connects to "
            f"{len(incoming)} incoming transmission path(s) and {len(outgoing)} outgoing path(s)."
        )

        # Price quote if ticker exists
        from . import market
        resolved = market.resolve_ticker(node_id)
        ticker = node.get("ticker") or resolved.get("ticker")
        price_info = None
        if ticker and resolved.get("status") != "no_data":
            try:
                now_d = datetime.now(timezone.utc)
                start_d = (now_d - timedelta(days=40)).strftime("%Y-%m-%d")
                end_d = now_d.strftime("%Y-%m-%d")
                bars = market.fetch_history(ticker, start_date=start_d, end_date=end_d, interval="1d", timeout=5.0)
                if bars and len(bars) >= 2:
                    p_curr = bars[-1]["close"]
                    p_prev = bars[-2]["close"]
                    pct = round((p_curr - p_prev) / p_prev * 100.0, 2) if p_prev > 0 else 0.0
                    spark = [round(b["close"], 2) for b in bars[-10:]]
                    price_info = {
                        "ticker": ticker,
                        "latest_price": round(p_curr, 2),
                        "latest_change_pct": pct,
                        "sparkline": spark,
                        "is_proxy": resolved.get("is_proxy", False),
                        "proxy_name": resolved.get("proxy_name"),
                    }
            except Exception:
                pass

        return {
            "node": node,
            "role": role,
            "summary": summary,
            "edges": incoming + outgoing,
            "incoming_edges": incoming,
            "outgoing_edges": outgoing,
            "supporting_articles": articles,
            "price_data": price_info,
        }

    def graph(
        self,
        article_id: Optional[str] = None,
        article_ids: Optional[List[str]] = None,
        sectors: Optional[List[str]] = None,
        depth: int = 2,
        kinds: Optional[List[str]] = None,
        types: Optional[List[str]] = None,
        sign: Optional[int] = None,
        min_conf: float = 0.0,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        include_events: bool = True,
    ) -> dict:
        """Graph query returning nodes and bundled edges with role classification,
        PageRank importance, plain-English labels, and multi-hop neighborhood filtering.
        """
        where = []
        args = []

        target_aids = []
        if article_id:
            target_aids.append(article_id)
        if article_ids:
            target_aids.extend([a for a in article_ids if a])

        if kinds:
            placeholders = ",".join("?" for _ in kinds)
            where.append(f"e.kind IN ({placeholders})")
            args.extend(kinds)
        if sign is not None:
            where.append("e.sign = ?")
            args.append(sign)
        if min_conf > 0:
            where.append("e.confidence >= ?")
            args.append(min_conf)

        where_sql = (" WHERE " + " AND ".join(where)) if where else ""
        sql = f"""SELECT e.*, e.source_id AS 'from', e.target_id AS 'to' FROM edges e {where_sql} ORDER BY e.id"""
        raw_edges = self._all(sql, tuple(args))

        # Filter and decorate with decayed confidence
        active_edges = []
        for e in raw_edges:
            e["confidence"] = self.calculate_decay(e)
            if e["confidence"] >= min_conf:
                art_count = len(json.loads(e.get("article_ids_json") or "[]"))
                if e["kind"] == "inferred" and (art_count >= 3 or (e.get("support_count") or 1) >= 3):
                    e["promoted"] = True
                    e["display_kind"] = "observed-supported"
                else:
                    e["promoted"] = False
                    e["display_kind"] = e["kind"]

                if from_date and (e.get("last_seen") or "") < from_date:
                    continue
                if to_date and (e.get("first_seen") or "") > to_date:
                    continue
                active_edges.append(e)

        # Build NetworkX graph for topology filtering and PageRank
        G = nx.DiGraph()
        for e in active_edges:
            G.add_edge(e["from"], e["to"], weight=max(0.1, float(e.get("strength", 0.5))))

        all_nodes_raw = self._all("SELECT * FROM nodes")
        nodes_dict = {}
        for n in all_nodes_raw:
            n = dict(n)
            n.pop("embedding", None)
            n["aliases"] = json.loads(n.get("aliases_json") or "[]")
            nodes_dict[n["id"]] = n
            if n["id"] not in G:
                G.add_node(n["id"])

        # Neighborhood sub-graph filtering if articles or sectors are requested
        filtered_node_ids = set()
        highlights = []

        if target_aids or sectors:
            seeds = set()
            if target_aids:
                for aid in target_aids:
                    ev_node = f"event:{aid}"
                    if ev_node in G:
                        seeds.add(ev_node)
                        highlights.append(ev_node)
                    # Also include articles touching edges
                    for e in active_edges:
                        if e.get("article_id") == aid or (aid in json.loads(e.get("article_ids_json") or "[]")):
                            seeds.add(e["from"])
                            seeds.add(e["to"])

            if sectors:
                for sec in sectors:
                    if sec in G:
                        seeds.add(sec)
                        highlights.append(sec)

            # Expand seeds by depth hops (undirected expansion)
            UG = G.to_undirected()
            for s in seeds:
                if s in UG:
                    lengths = nx.single_source_shortest_path_length(UG, s, cutoff=depth)
                    filtered_node_ids.update(lengths.keys())

            # Restrict active_edges to those within the filtered set
            active_edges = [
                e for e in active_edges
                if e["from"] in filtered_node_ids and e["to"] in filtered_node_ids
            ]
            # Rebuild G for filtered subgraph
            G = nx.DiGraph()
            for e in active_edges:
                G.add_edge(e["from"], e["to"], weight=max(0.1, float(e.get("strength", 0.5))))
        else:
            filtered_node_ids = set(G.nodes)

        # Remove Event nodes if include_events is False
        if not include_events:
            event_nodes = {nid for nid in filtered_node_ids if nodes_dict.get(nid, {}).get("type") == "Event" or nid.startswith("event:")}
            filtered_node_ids -= event_nodes
            active_edges = [e for e in active_edges if e["from"] not in event_nodes and e["to"] not in event_nodes]
            G.remove_nodes_from(event_nodes)

        # PageRank importance computation
        pr_scores = {}
        if len(G) > 0:
            try:
                pr_scores = nx.pagerank(G, weight="weight")
            except Exception:
                pr_scores = {nid: 1.0 / len(G) for nid in G}

        max_pr = max(pr_scores.values()) if pr_scores else 1.0

        # Edge Bundling: merge parallel edges between same (src, tgt) pair
        pair_groups = {}
        for e in active_edges:
            pair_groups.setdefault((e["from"], e["to"]), []).append(e)

        bundled_edges = []
        for (src, tgt), grp in pair_groups.items():
            best = max(grp, key=lambda x: (x.get("confidence", 0.0), x.get("strength", 0.0)))
            signs = {x["sign"] for x in grp}
            has_real_conflict = 1 if len(signs) > 1 else (1 if any(x.get("conflict") for x in grp) else 0)
            sign_sym = "▲" if best["sign"] > 0 else "▼"
            conf_pct = int(best["confidence"] * 100)

            if len(grp) == 1:
                e_copy = dict(best)
                e_copy["badge"] = None
                e_copy["bundle_count"] = 1
                e_copy["bundled_edges"] = [best]
                e_copy["conflict"] = has_real_conflict
                e_copy["label"] = f"{best['relation']} {sign_sym} {conf_pct}%"
                bundled_edges.append(e_copy)
            else:
                bundled_edges.append({
                    "id": f"bundle-{src}-{tgt}",
                    "from": src,
                    "to": tgt,
                    "source_id": src,
                    "target_id": tgt,
                    "relation": best["relation"],
                    "sign": best["sign"],
                    "strength": max(x.get("strength", 0.5) for x in grp),
                    "confidence": max(x.get("confidence", 0.5) for x in grp),
                    "kind": best["kind"],
                    "reason": best.get("reason", ""),
                    "evidence_text": best.get("evidence_text", ""),
                    "article_id": best.get("article_id"),
                    "article_ids_json": json.dumps(list({aid for x in grp for aid in json.loads(x.get("article_ids_json") or "[]")})),
                    "support_count": sum(x.get("support_count", 1) for x in grp),
                    "first_seen": min((x.get("first_seen") or "9999") for x in grp),
                    "last_seen": max((x.get("last_seen") or "0000") for x in grp),
                    "conflict": has_real_conflict,
                    "badge": f"x{len(grp)}",
                    "bundle_count": len(grp),
                    "bundled_edges": grp,
                    "label": f"{best['relation']} {sign_sym} {conf_pct}% (x{len(grp)})",
                    "display_kind": best.get("display_kind", best.get("kind")),
                })

        # Assemble node list with roles, importance, shapes, and halo styles
        nodes = []
        role_counts = {}
        type_counts = {}

        for nid in filtered_node_ids:
            n = nodes_dict.get(nid)
            if not n:
                ntype = "Event" if nid.startswith("event:") else "Company"
                n = {"id": nid, "label": nid, "type": ntype, "aliases": []}

            ntype = n.get("type", "Company")
            if types and ntype not in types:
                continue

            # In/Out degree in active G
            in_deg = G.in_degree(nid) if nid in G else 0
            out_deg = G.out_degree(nid) if nid in G else 0

            # Role assignment
            if ntype == "Event" or nid.startswith("event:"):
                role = "Event"
            elif ntype == "Sector":
                role = "Sector"
            elif in_deg == 0 and out_deg > 0:
                role = "Trigger/Driver"
            elif in_deg > 0 and out_deg == 0:
                role = "Receiver/Asset"
            else:
                role = "Transmitter"

            role_colors = {
                "Trigger/Driver": "#f59e0b",
                "Transmitter":    "#a855f7",
                "Sector":         "#06b6d4",
                "Receiver/Asset": "#3b82f6",
                "Event":          "#ec4899",
            }
            ring_color = role_colors.get(role, "#3b82f6")

            # Importance normalized 0.1 - 1.0
            raw_pr = pr_scores.get(nid, 0.0)
            importance = round(0.1 + 0.9 * (raw_pr / max_pr), 2) if max_pr > 0 else 0.5

            # Short label for Event nodes (dd Mon · short title <= 36 chars)
            lbl = n.get("label") or nid
            if role == "Event":
                # Find matching article
                aid = nid.replace("event:", "")
                art_row = self._one("SELECT title, published_at FROM articles WHERE id=?", (aid,))
                if art_row:
                    pub = art_row.get("published_at") or ""
                    d_prefix = ""
                    if len(pub) >= 10:
                        try:
                            d_prefix = datetime.strptime(pub[:10], "%Y-%m-%d").strftime("%d %b · ")
                        except Exception:
                            pass
                    lbl = (d_prefix + art_row.get("title", ""))[:36]
                    if len(art_row.get("title", "")) > 36:
                        lbl += "…"

            n_copy = dict(n)
            n_copy["role"] = role
            n_copy["ring_color"] = ring_color
            n_copy["importance"] = importance
            n_copy["display_label"] = lbl
            n_copy["in_degree"] = in_deg
            n_copy["out_degree"] = out_deg
            nodes.append(n_copy)

            role_counts[role] = role_counts.get(role, 0) + 1
            type_counts[ntype] = type_counts.get(ntype, 0) + 1

        meta = {
            "total_nodes": len(nodes),
            "total_edges": len(bundled_edges),
            "roles": role_counts,
            "types": type_counts,
            "filtered_articles": target_aids,
            "filtered_sectors": sectors or [],
        }

        return {
            "nodes": nodes,
            "edges": bundled_edges,
            "meta": meta,
            "highlights": highlights,
        }

    def sectors(self) -> List[dict]:
        rows = self._all(
            """SELECT sector, AVG(score) AS avg_score, COUNT(*) AS n, SUM(ABS(score)) AS weight
               FROM sector_impacts GROUP BY sector"""
        )
        total = sum(r["weight"] for r in rows) or 1.0
        for r in rows:
            last = self._one(
                """SELECT s.score, s.explanation, a.title, s.published_at FROM sector_impacts s
                   JOIN articles a ON a.id=s.article_id WHERE s.sector=?
                   ORDER BY s.published_at DESC LIMIT 1""",
                (r["sector"],),
            )
            r["avg_score"] = round(r["avg_score"], 3)
            r["share_pct"] = round(100 * r.pop("weight") / total, 1)
            r["direction"] = "positive" if r["avg_score"] > 0.1 else "negative" if r["avg_score"] < -0.1 else "mixed"
            r["latest"] = last
        return sorted(rows, key=lambda r: -r["share_pct"])

    def timeseries(self, sector: Optional[str] = None, alpha: float = 0.6, include_demo: bool = False) -> dict:
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        demo_cond = "" if include_demo else " AND (s.is_demo = 0 OR s.is_demo IS NULL) AND substr(s.published_at, 1, 10) NOT IN ('2022-02-24', '2024-01-01')"
        sql = f"""
            SELECT s.sector, substr(s.published_at, 1, 10) AS date, s.score, s.article_id,
                   COALESCE(a.title, '') AS article_title, s.published_at
            FROM sector_impacts s
            LEFT JOIN articles a ON a.id = s.article_id
            WHERE substr(s.published_at, 1, 10) <= ?
            {demo_cond}
        """
        args = [today_str]
        if sector:
            sql += " AND s.sector=?"
            args.append(sector)
        sql += " ORDER BY s.sector, s.published_at ASC"

        rows = self._all(sql, tuple(args))
        out = {}
        for r in rows:
            pts = out.setdefault(r["sector"], [])
            prev_ema = pts[-1]["ema"] if pts else r["score"]
            cum = (pts[-1]["cumulative"] if pts else 0.0) + r["score"]
            pts.append({
                "date": r["date"],
                "published_at": r["published_at"],
                "score": round(r["score"], 3),
                "article_id": r["article_id"],
                "article_title": r["article_title"],
                "count": 1,
                "ema": round(alpha * r["score"] + (1 - alpha) * prev_ema, 3),
                "cumulative": round(cum, 3),
            })
        return out

    def revisions(self, article_id: Optional[str] = None) -> List[dict]:
        rows = self._all(
            """SELECT r.*, n.title AS new_title, n.published_at AS new_date, p.title AS prior_title,
                      p.published_at AS prior_date FROM revisions r
               JOIN articles n ON n.id=r.article_id
               JOIN articles p ON p.id=r.prior_article_id """
            + (" WHERE r.article_id=?" if article_id else "")
            + """ ORDER BY n.published_at DESC, r.id""",
            (article_id,) if article_id else (),
        )
        for r in rows:
            for k in ("deltas", "pros", "cons"):
                r[k] = json.loads(r.pop(f"{k}_json") or "[]")
        return rows

    def stats(self) -> dict:
        counts = {
            t: self._one(f"SELECT COUNT(*) AS c FROM {t}")["c"]
            for t in ("articles", "nodes", "edges", "sector_impacts", "revisions")
        }
        observed = self._one("SELECT COUNT(*) AS c FROM edges WHERE kind='observed'")["c"]
        inferred = self._one("SELECT COUNT(*) AS c FROM edges WHERE kind='inferred'")["c"]
        knowledge = self._one("SELECT COUNT(*) AS c FROM edges WHERE kind='knowledge'")["c"]
        counts["observed_edges"] = observed
        counts["inferred_edges"] = inferred
        counts["knowledge_edges"] = knowledge
        try:
            counts["inbox"] = self._one("SELECT COUNT(*) AS c FROM news_inbox")["c"]
        except Exception:
            counts["inbox"] = 0
        return counts

    # ------------------------------------------------------------ news inbox
    def inbox_upsert(self, items: List[dict]) -> int:
        """Upsert raw Marketaux articles into news_inbox. Returns count of new rows."""
        new_count = 0
        now = _now()
        with self.lock, self.db:
            for item in items:
                uuid = item.get("uuid") or ""
                url = item.get("url") or ""
                if not uuid and not url:
                    continue
                cur = self.db.execute(
                    """INSERT OR IGNORE INTO news_inbox
                       (uuid, title, description, url, source, published_at, image_url,
                        entities_json, sentiment_marketaux, fetched_at, status, search_query)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        uuid,
                        item.get("title", ""),
                        item.get("description", ""),
                        url,
                        item.get("source", ""),
                        item.get("published_at", ""),
                        item.get("image_url"),
                        json.dumps(item.get("entities", [])),
                        item.get("sentiment_marketaux"),
                        now,
                        "new",
                        item.get("search_query"),
                    ),
                )
                if cur.rowcount:
                    new_count += 1
        return new_count

    def inbox_list(self, status: Optional[str] = None, limit: int = 100) -> List[dict]:
        """Return inbox items, optionally filtered by status."""
        sql = "SELECT * FROM news_inbox"
        args: tuple = ()
        if status in ("new", "pending"):
            sql += " WHERE status IN ('new', 'pending')"
        elif status:
            sql += " WHERE status=?"
            args = (status,)
        sql += " ORDER BY published_at DESC LIMIT ?"
        args = args + (limit,)
        rows = self._all(sql, args)
        for r in rows:
            try:
                r["entities"] = json.loads(r.get("entities_json") or "[]")
            except Exception:
                r["entities"] = []
            # Check if in KG already
            art_id = r.get("uuid") or ""
            r["in_kg"] = bool(self._one("SELECT 1 FROM articles WHERE id=?", (art_id,)))
        return rows

    def inbox_mark_analyzed(self, uuid: str) -> None:
        with self.lock, self.db:
            self.db.execute("UPDATE news_inbox SET status='analyzed' WHERE uuid=?", (uuid,))

    def inbox_get(self, uuid: str) -> Optional[dict]:
        row = self._one("SELECT * FROM news_inbox WHERE uuid=?", (uuid,))
        if row:
            try:
                row["entities"] = json.loads(row.get("entities_json") or "[]")
            except Exception:
                row["entities"] = []
        return row
