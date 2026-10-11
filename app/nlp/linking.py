"""Entity Linking: maps mentions to canonical Knowledge Graph nodes.
Uses:
  1. Exact alias / label lookup from seed KB / graph
  2. MiniLM embedding similarity with threshold >= 0.55 (NEWSGRAPH_LINK_MIN)
  3. Fallback unlinked node typed by spaCy label
"""
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

from .base import cached_result

LABEL_TYPE_MAP = {
    "ORG": "Company",
    "GPE": "Macro",
    "LOC": "Macro",
    "PERSON": "Person",
    "MONEY": "Indicator",
    "PERCENT": "Indicator",
    "QUANTITY": "Indicator",
    "DATE": "Date",
}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


class EntityLinker:
    _instance: Optional["EntityLinker"] = None

    def __init__(self, seed_path: Optional[str] = None):
        if not seed_path:
            p = Path(__file__).resolve().parent.parent.parent / "data" / "seed_kb.json"
            seed_path = str(p)
        self.seed_path = seed_path
        self.nodes: Dict[str, Dict[str, Any]] = {}
        self.alias_map: Dict[str, str] = {}
        self.candidate_texts: List[str] = []
        self.candidate_node_ids: List[str] = []
        self._load_seed()

    def _load_seed(self):
        if os.path.exists(self.seed_path):
            try:
                data = json.loads(Path(self.seed_path).read_text(encoding="utf-8"))
                for n in data.get("nodes", []):
                    nid = n["id"]
                    self.nodes[nid] = n
                    self.alias_map[_norm(nid)] = nid
                    self.candidate_texts.append(nid)
                    self.candidate_node_ids.append(nid)
                    for a in n.get("aliases", []):
                        na = _norm(a)
                        if na:
                            self.alias_map[na] = nid
                            self.candidate_texts.append(a)
                            self.candidate_node_ids.append(nid)
            except Exception:
                pass

    def add_node(self, node_id: str, node_type: str, aliases: Optional[List[str]] = None, ticker: Optional[str] = None):
        self.nodes[node_id] = {"id": node_id, "type": node_type, "ticker": ticker, "aliases": aliases or []}
        self.alias_map[_norm(node_id)] = node_id
        for a in aliases or []:
            na = _norm(a)
            if na:
                self.alias_map[na] = node_id

    def link_mention(self, text: str, spacy_label: str, embedder=None) -> Dict[str, Any]:
        """Link a single mention to canonical KG node."""
        norm_text = _norm(text)
        if not norm_text:
            return {
                "linked_node_id": text,
                "node_type": LABEL_TYPE_MAP.get(spacy_label, "Company"),
                "link_score": 0.0,
                "linked": False,
                "ticker": None,
            }

        # 1. Exact alias / label match
        if norm_text in self.alias_map:
            canon_id = self.alias_map[norm_text]
            node = self.nodes.get(canon_id, {})
            return {
                "linked_node_id": canon_id,
                "node_type": node.get("type", LABEL_TYPE_MAP.get(spacy_label, "Company")),
                "link_score": 1.0,
                "linked": True,
                "ticker": node.get("ticker"),
            }

        # Check substring matches in aliases (e.g., 'Brent' in 'brent crude' or 'brent crude' contains 'brent')
        for alias_key, canon_id in self.alias_map.items():
            if alias_key and len(alias_key) >= 3 and (norm_text == alias_key or f" {norm_text} " in f" {alias_key} " or f" {alias_key} " in f" {norm_text} "):
                node = self.nodes.get(canon_id, {})
                return {
                    "linked_node_id": canon_id,
                    "node_type": node.get("type", LABEL_TYPE_MAP.get(spacy_label, "Company")),
                    "link_score": 0.95,
                    "linked": True,
                    "ticker": node.get("ticker"),
                }

        # 2. Embedding semantic match (MiniLM)
        threshold = float(os.getenv("NEWSGRAPH_LINK_MIN", "0.55"))
        if embedder is not None and self.candidate_texts:
            best_score = 0.0
            best_id = None
            try:
                mention_emb = embedder.embed(text)
                cand_embs = embedder.embed_batch(self.candidate_texts)
                sims = np.dot(cand_embs, mention_emb) / (
                    np.linalg.norm(cand_embs, axis=1) * np.linalg.norm(mention_emb) + 1e-9
                )
                best_idx = int(np.argmax(sims))
                best_score = float(sims[best_idx])
                if best_score >= threshold:
                    best_id = self.candidate_node_ids[best_idx]
            except Exception:
                pass

            if best_id and best_score >= threshold:
                node = self.nodes.get(best_id, {})
                return {
                    "linked_node_id": best_id,
                    "node_type": node.get("type", LABEL_TYPE_MAP.get(spacy_label, "Company")),
                    "link_score": round(best_score, 3),
                    "linked": True,
                    "ticker": node.get("ticker"),
                }

        # 3. Fallback unlinked node
        return {
            "linked_node_id": text,
            "node_type": LABEL_TYPE_MAP.get(spacy_label, "Company"),
            "link_score": 0.0,
            "linked": False,
            "ticker": None,
        }


_LINKER: Optional[EntityLinker] = None


def get_linker() -> EntityLinker:
    global _LINKER
    if _LINKER is None:
        _LINKER = EntityLinker()
    return _LINKER
