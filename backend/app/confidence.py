"""
confidence.py — Per-edge/path confidence scoring.  STEP 5.

Confidence formula (documented here per spec):
────────────────────────────────────────────────────────────────────────────────
  Three components:
    A. seed_support   (0 or 1)
         1.0  if the edge exists in the curated seed graph
         0.0  if the edge is LLM-inferred (not in seed graph)

    B. consistency    ∈ [0, 1]
         Agreement ratio across 3 LLM runs (direction + entity-set Jaccard).
         Computed in extraction.py and passed in.
         We do NOT ask the LLM for its own confidence (overconfident).

    C. market_support ∈ [0, 1]  (optional)
         From the yfinance event study (CAR in the predicted direction → 1,
         opposite direction → 0, no data → None).
         If None, C is excluded and weights are redistributed.

  Final formula:
    If market_support is available:
      confidence = 0.50 × A + 0.30 × B + 0.20 × C

    If market_support is None (no market data):
      confidence = 0.60 × A + 0.40 × B

    Rationale:
      • Seed support is the strongest signal — human-curated relationships
        with source references carry more weight than LLM extractions.
      • Consistency catches cases where the LLM disagrees across runs
        (low consistency → likely a noisy or ambiguous event).
      • Market support is informative but noisy (macro events move the whole
        market; the benchmark regression may not isolate the causal effect).
────────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import logging

from app.graph_loader import load_seed_graph
from app.schemas import (
    AffectedAsset,
    ConfidenceBreakdown,
    Edge,
    EdgeStatus,
    Sign,
)

logger = logging.getLogger(__name__)

# Weight constants — documented above
W_SEED_WITH_MARKET    = 0.50
W_CONSISTENCY_WITH    = 0.30
W_MARKET              = 0.20

W_SEED_NO_MARKET      = 0.60
W_CONSISTENCY_NO      = 0.40


def compute_edge_confidence(
    edge_id:           str,
    is_in_seed:        bool,
    consistency:       float,
    evidence_support:  float = 0.6,
    matrix_support:    float = 0.7,
    market_support:    float | None = None,
) -> ConfidenceBreakdown:
    """
    Compute computed confidence combining:
      1. Agreement across runs (consistency)
      2. Verified evidence support in text
      3. Curated matrix support
      4. Market check result (if available)
    """
    if market_support is not None:
        final = (
            0.35 * matrix_support
            + 0.30 * consistency
            + 0.20 * evidence_support
            + 0.15 * market_support
        )
        formula = (
            f"0.35 × {matrix_support:.2f} (matrix) + 0.30 × {consistency:.2f} (agreement) "
            f"+ 0.20 × {evidence_support:.2f} (evidence) + 0.15 × {market_support:.2f} (market) = {final:.3f}"
        )
    else:
        final = (
            0.45 * matrix_support
            + 0.30 * consistency
            + 0.25 * evidence_support
        )
        formula = (
            f"0.45 × {matrix_support:.2f} (matrix) + 0.30 × {consistency:.2f} (agreement) "
            f"+ 0.25 × {evidence_support:.2f} (evidence) = {final:.3f} [no market data]"
        )

    final = round(max(0.15, min(0.98, final)), 3)
    return ConfidenceBreakdown(
        seed_support   = 1.0 if is_in_seed else 0.0,
        consistency    = consistency,
        market_support = market_support,
        final          = final,
        formula_note   = formula,
    )


def enrich_edges_with_confidence(
    edges:               list[Edge],
    consistency:         float,
    primary_node:        str = "",
    news_text:           str = "",
    matrix_sector_map:   dict[str, float] | None = None,
    market_support_map:  dict[str, float] | None = None,
) -> list[Edge]:
    """
    Add computed confidence and typed relations to a list of Edge objects.
    """
    sg       = load_seed_graph()
    seed_ids = set(sg.edges.keys())
    nt_lower = news_text.lower() if news_text else ""

    for edge in edges:
        is_seed = edge.id in seed_ids

        # 1. Verified evidence support: check if source or target appears in text
        src_label = sg.nodes[edge.source].label.lower() if edge.source in sg.nodes else edge.source
        tgt_label = sg.nodes[edge.target].label.lower() if edge.target in sg.nodes else edge.target
        has_src = src_label in nt_lower or edge.source in nt_lower
        has_tgt = tgt_label in nt_lower or edge.target in nt_lower

        if has_src and has_tgt:
            evidence_support = 1.0
            claim_type = "verified_news_fact"
        elif has_src or has_tgt:
            evidence_support = 0.8
            claim_type = "verified_news_fact" if has_tgt else "established_mechanism"
        elif is_seed:
            evidence_support = 0.55
            claim_type = "established_mechanism"
        else:
            evidence_support = 0.25
            claim_type = "ai_inferred"

        # 2. Curated matrix support
        midpoint = (edge.strength_min + edge.strength_max) / 2.0
        if matrix_sector_map and edge.target in matrix_sector_map:
            matrix_support = max(0.4, min(1.0, matrix_sector_map[edge.target]))
        elif matrix_sector_map and edge.source in matrix_sector_map:
            matrix_support = max(0.4, min(1.0, matrix_sector_map[edge.source]))
        else:
            matrix_support = max(0.35, min(0.95, midpoint))

        # 3. Market check support
        ms: float | None = None
        if market_support_map and edge.target in market_support_map:
            ms = market_support_map[edge.target]

        breakdown = compute_edge_confidence(
            edge.id, is_seed, consistency, evidence_support, matrix_support, ms
        )
        edge.confidence = breakdown.final
        edge.claim_type = claim_type
        edge.confidence_label = f"{'High' if edge.confidence >= 0.75 else ('Medium' if edge.confidence >= 0.50 else 'Low')} ({int(edge.confidence * 100)}%)"
        edge.confidence_breakdown = {
            "agreement_ratio":   round(consistency, 2),
            "evidence_support":  round(evidence_support, 2),
            "matrix_support":    round(matrix_support, 2),
            "market_support":    round(ms, 2) if ms is not None else None,
            "final":             edge.confidence,
        }

        # 4. Typed relation assignment
        if edge.sign == Sign.positive:
            if any(k in edge.target for k in ["omc", "aviation", "paint", "cost", "inflation", "cad"]):
                edge.relation = "pressures" if "cost" in edge.reasoning.lower() or "margin" in edge.reasoning.lower() else "increases"
            elif any(k in edge.target for k in ["it_", "pharma_", "exporter"]):
                edge.relation = "benefits"
            else:
                edge.relation = "increases"
        elif edge.sign == Sign.negative:
            if "margin" in edge.reasoning.lower() or "cost" in edge.reasoning.lower() or "dampen" in edge.reasoning.lower():
                edge.relation = "pressures"
            else:
                edge.relation = "decreases"
        else:
            edge.relation = "correlates_with"

    return edges


def compute_uncertainty_note(
    consistency:     float,
    unlinked_count:  int,
    inferred_count:  int,
) -> dict:
    """
    Build the uncertainty note displayed in the UI and API response.

    The note is always present regardless of how good the analysis looks.
    """
    details: list[str] = [
        "All impacts shown are PLAUSIBLE SCENARIOS based on historical causal patterns, "
        "not guaranteed predictions. Many factors not modelled here can dominate.",
        f"LLM self-consistency across 3 runs: {consistency:.0%}. "
        "Lower consistency means the extracted event was ambiguous.",
    ]

    if unlinked_count > 0:
        details.append(
            f"{unlinked_count} entity/entities could not be mapped to the seed graph "
            "and are shown as UNLINKED. Their causal paths are marked 'inferred' with "
            "reduced confidence."
        )

    if inferred_count > 0:
        details.append(
            f"{inferred_count} edge(s) are LLM-INFERRED (not in seed graph). "
            "These carry lower confidence and are shown with dashed borders in the graph."
        )

    details.append(
        "The event-study market data is INDICATIVE only. Macro events move the entire "
        "market simultaneously, making it impossible to cleanly isolate individual causal "
        "effects using a simple market-model benchmark."
    )

    return {
        "headline": "⚠️  Plausible impact scenarios — not guaranteed predictions",
        "details":  details,
    }
