"""
propagation.py — Signed, decayed causal propagation over the seed graph. STEP 4.

Algorithm:
    1. Start from the event's primary_node.
    2. BFS over the DiGraph up to MAX_DEPTH hops.
    3. Track sign (product of edge signs along path) and score
       (product of edge midpoint weights × PER_HOP_DECAY^(hops-1)).
    4. Skip a node if it already appears in the current path (cycle prevention).
    5. Collect all paths, sort by |score| descending, return TOP_K.
    6. Aggregate affected_assets from all terminal nodes with their best path.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import NamedTuple

import networkx as nx

from app.graph_loader import load_seed_graph
from app.schemas import (
    AffectedAsset,
    EdgeStatus,
    ExtractedEvent,
    Lag,
    Node,
    NodeType,
    PathResult,
    Sign,
)

logger = logging.getLogger(__name__)

MAX_DEPTH      = 4      # maximum hops from event node
PER_HOP_DECAY  = 0.75   # applied once per additional hop beyond the first
TOP_K_PATHS    = 12     # paths returned in the response
TOP_K_ASSETS   = 10     # affected assets returned


# ─── Sign arithmetic ──────────────────────────────────────────────────────────

_SIGN_PRODUCT: dict[tuple[str, str], Sign] = {
    ("+", "+"): Sign.positive,
    ("+", "-"): Sign.negative,
    ("-", "+"): Sign.negative,
    ("-", "-"): Sign.positive,
    ("+", "?"): Sign.ambiguous,
    ("-", "?"): Sign.ambiguous,
    ("?", "+"): Sign.ambiguous,
    ("?", "-"): Sign.ambiguous,
    ("?", "?"): Sign.ambiguous,
}


def multiply_signs(s1: Sign, s2: Sign) -> Sign:
    """Propagate sign through a causal chain: + × - = -, - × - = +, ? propagates."""
    return _SIGN_PRODUCT.get((s1.value, s2.value), Sign.ambiguous)


# ─── Path state during BFS ────────────────────────────────────────────────────

class _PathState(NamedTuple):
    node_ids:  tuple[str, ...]   # visited node IDs (in order)
    edge_ids:  tuple[str, ...]   # traversed edge IDs
    sign:      Sign
    score:     float             # running score (product of weights × decay)
    hop_count: int


# ─── Main propagation function ────────────────────────────────────────────────

def propagate(event: ExtractedEvent) -> tuple[list[PathResult], list[AffectedAsset]]:
    """
    Run signed, decayed propagation from the event node.

    Returns:
        top_paths:       TOP_K_PATHS PathResult objects (sorted by |score| desc)
        affected_assets: TOP_K_ASSETS AffectedAsset objects
    """
    sg = load_seed_graph()
    G  = sg.G

    # Resolve start node; if UNLINKED, we have no starting point in the graph
    start_id = event.primary_node
    if start_id.startswith("UNLINKED:"):
        logger.warning("Primary node is unlinked — propagation cannot start: %s", start_id)
        return [], []

    if start_id not in G:
        logger.warning("Primary node '%s' not in graph", start_id)
        return [], []

    # Determine event direction (flip the graph edges if event direction is -)
    # Convention: if event.direction == "+", source rises → propagate normally.
    # If "-", source falls → flip the sign of the first edge.
    event_sign = event.direction

    # ── BFS ────────────────────────────────────────────────────────────────────
    completed_paths: list[_PathState] = []

    # Initial state: at start_id, no edges traversed yet
    frontier: list[_PathState] = [
        _PathState(
            node_ids  = (start_id,),
            edge_ids  = (),
            sign      = event_sign,   # direction of the event itself
            score     = 1.0,
            hop_count = 0,
        )
    ]

    while frontier:
        current = frontier.pop(0)

        # Expand neighbors
        last_node = current.node_ids[-1]
        neighbors = list(G.successors(last_node))

        expanded = False
        for neighbor in neighbors:
            # Cycle prevention: skip if already in path
            if neighbor in current.node_ids:
                continue

            edge_data = G.edges[last_node, neighbor]
            edge_id   = edge_data["id"]
            edge_sign = Sign(edge_data["sign"])
            midpoint  = edge_data["midpoint"]

            # Propagated sign
            new_sign = multiply_signs(current.sign, edge_sign)

            # Score: midpoint weight × decay for hops beyond 1
            decay_factor = PER_HOP_DECAY ** current.hop_count  # decays with each additional hop
            new_score    = current.score * midpoint * decay_factor

            new_state = _PathState(
                node_ids  = current.node_ids + (neighbor,),
                edge_ids  = current.edge_ids + (edge_id,),
                sign      = new_sign,
                score     = new_score,
                hop_count = current.hop_count + 1,
            )

            # Record this path (every endpoint is a valid propagation path)
            completed_paths.append(new_state)

            # Continue BFS if within depth limit
            if current.hop_count + 1 < MAX_DEPTH:
                frontier.append(new_state)
            expanded = True

        # If no expansion (terminal node or max depth), still record if 1+ hops
        # (already recorded above in the loop)
        _ = expanded

    # ── Rank and select top-k paths ────────────────────────────────────────────
    # Filter paths with at least 1 hop and sort by absolute score descending
    valid_paths = [p for p in completed_paths if p.hop_count >= 1]
    valid_paths.sort(key=lambda p: -p.score)
    top_paths_raw = valid_paths[:TOP_K_PATHS]

    # ── Convert to PathResult ──────────────────────────────────────────────────
    path_results: list[PathResult] = []
    for p in top_paths_raw:
        node_labels = [
            sg.nodes[nid].label if nid in sg.nodes else nid
            for nid in p.node_ids
        ]
        sign_symbol = p.sign.value
        summary = " → ".join(node_labels) + f"  ({sign_symbol})"

        path_results.append(PathResult(
            nodes      = list(p.node_ids),
            edge_ids   = list(p.edge_ids),
            path_score = round(p.score, 4),
            sign       = p.sign,
            hop_count  = p.hop_count,
            summary    = summary,
        ))

    # ── Aggregate affected assets ──────────────────────────────────────────────
    # For each terminal node, collect the best path reaching it
    best_path_by_node: dict[str, _PathState] = {}
    path_count_by_node: dict[str, int] = defaultdict(int)

    for p in valid_paths:
        terminal = p.node_ids[-1]
        if terminal == start_id:
            continue
        path_count_by_node[terminal] += 1
        if terminal not in best_path_by_node or p.score > best_path_by_node[terminal].score:
            best_path_by_node[terminal] = p

    # Sort by best path score and pick top k
    sorted_assets = sorted(
        best_path_by_node.items(),
        key=lambda kv: -kv[1].score,
    )[:TOP_K_ASSETS]

    affected_assets: list[AffectedAsset] = []
    for node_id, best in sorted_assets:
        node = sg.nodes.get(node_id)
        if node is None:
            continue

        # Reasoning: combine edge reasonings on the best path
        path_edge_reasons = []
        for eid in best.edge_ids:
            e = sg.edges.get(eid)
            if e:
                path_edge_reasons.append(e.reasoning[:100])

        reasoning = f"Via {best.hop_count}-hop chain: " + "; ".join(path_edge_reasons[:2])

        affected_assets.append(AffectedAsset(
            node_id    = node_id,
            label      = node.label,
            node_type  = node.type,
            direction  = best.sign,
            confidence = round(min(best.score, 1.0), 3),
            paths      = path_count_by_node[node_id],
            reasoning  = reasoning,
        ))

    return path_results, affected_assets
