"""
graph_loader.py — Loads, validates and caches the seed graph.  STEP 2.

Exports:
    load_seed_graph()  -> SeedGraph (named tuple with G, nodes, edges, alias_map)
    resolve_alias(name) -> canonical seed node id or None

Validation rules (from STEP 2 spec):
    1. No dangling nodes (every edge source/target must be a declared node).
    2. Valid signs: only "+", "-", "?".
    3. strength_range: 0 <= min <= max <= 1.
    4. No isolated nodes (every node must appear in at least one edge).
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import NamedTuple

import networkx as nx

from app.schemas import Node, NodeType, SeedEdge, Sign, Lag

logger = logging.getLogger(__name__)

SEED_GRAPH_PATH = Path(__file__).parent / "seed_graph.json"


class SeedGraph(NamedTuple):
    G:         nx.DiGraph                  # networkx directed graph
    nodes:     dict[str, Node]             # node_id → Node
    edges:     dict[str, SeedEdge]         # edge_id → SeedEdge
    alias_map: dict[str, str]             # alias (lowercase) → canonical node_id


def _validate(
    nodes: dict[str, Node],
    edges: dict[str, SeedEdge],
) -> list[str]:
    """Return a list of validation error strings.  Empty list → graph is valid."""
    errors: list[str] = []
    node_ids = set(nodes.keys())
    connected: set[str] = set()

    for edge_id, edge in edges.items():
        # Rule 1: no dangling nodes
        if edge.source not in node_ids:
            errors.append(f"Edge {edge_id}: source '{edge.source}' not in nodes")
        if edge.target not in node_ids:
            errors.append(f"Edge {edge_id}: target '{edge.target}' not in nodes")
        else:
            connected.add(edge.source)
            connected.add(edge.target)

        # Rule 2+3: strength range (already enforced by SeedEdge validator)
        # (Pydantic will raise before we get here)

    # Rule 4: no isolated nodes
    isolated = node_ids - connected
    for nid in isolated:
        errors.append(f"Node '{nid}' is isolated (not connected to any edge)")

    return errors


@lru_cache(maxsize=1)
def load_seed_graph() -> SeedGraph:
    """Load seed_graph.json, validate, and return a SeedGraph.

    Uses lru_cache so the file is read only once per process.
    """
    raw = json.loads(SEED_GRAPH_PATH.read_text(encoding="utf-8"))

    # --- Parse nodes ---
    nodes: dict[str, Node] = {}
    for n in raw["nodes"]:
        node = Node(
            id=n["id"],
            label=n["label"],
            type=NodeType(n["type"]),
            description=n.get("description"),
            ticker=n.get("ticker"),
        )
        nodes[node.id] = node

    # --- Parse edges (Pydantic validates strength_range here) ---
    edges: dict[str, SeedEdge] = {}
    for e in raw["edges"]:
        se = SeedEdge(
            id=e["id"],
            source=e["source"],
            target=e["target"],
            sign=Sign(e["sign"]),
            strength_range=e["strength_range"],
            lag=Lag(e["lag"]),
            reasoning=e["reasoning"],
            source_ref=e["source_ref"],
        )
        edges[se.id] = se

    # --- Validate ---
    errors = _validate(nodes, edges)
    if errors:
        msg = "Seed graph validation failed:\n" + "\n".join(f"  • {e}" for e in errors)
        raise RuntimeError(msg)

    # --- Build NetworkX DiGraph ---
    G: nx.DiGraph = nx.DiGraph()
    for nid, node in nodes.items():
        G.add_node(nid, **node.model_dump())
    for eid, edge in edges.items():
        lo, hi = edge.strength_range
        G.add_edge(
            edge.source,
            edge.target,
            id=eid,
            sign=edge.sign.value,
            strength_min=lo,
            strength_max=hi,
            midpoint=(lo + hi) / 2,
            lag=edge.lag.value,
            reasoning=edge.reasoning,
            source_ref=edge.source_ref,
        )

    # --- Alias map (lower-cased for case-insensitive matching) ---
    alias_map: dict[str, str] = {
        k.lower(): v for k, v in raw.get("alias_map", {}).items()
    }
    # Add node IDs as self-aliases
    for nid in nodes:
        alias_map[nid.lower()] = nid

    logger.info(
        "Seed graph loaded: %d nodes, %d edges, %d aliases",
        len(nodes), len(edges), len(alias_map),
    )
    return SeedGraph(G=G, nodes=nodes, edges=edges, alias_map=alias_map)


def resolve_alias(name: str) -> str | None:
    """Map a free-text entity name to a canonical seed node id.

    Returns None if no match found. Tries:
      1. Exact match in alias_map.
      2. Token match against words in the input.
      3. Substring match only for aliases of length >= 4 to avoid false hits on short aliases (e.g. 'it', 'cad').
    """
    sg = load_seed_graph()
    key = name.lower().strip().replace(" ", "_").replace("-", "_")

    # 1. Exact
    if key in sg.alias_map:
        return sg.alias_map[key]

    tokens = set(key.split("_"))

    # 2. Token match (e.g. "brent" in "brent_crude", or "it" in "it_stocks")
    for alias, canonical in sg.alias_map.items():
        if alias in tokens:
            return canonical

    # 3. Substring match only for aliases with >= 4 characters
    for alias, canonical in sg.alias_map.items():
        if len(alias) >= 4 and (alias in key or (len(key) >= 4 and key in alias)):
            return canonical

    return None
