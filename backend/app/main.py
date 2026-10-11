"""
main.py — FastAPI application for Market Impact Graph.  STEPS 0 + 7.

Routes:
    GET  /health                  — liveness check
    GET  /seed-graph              — return the full seed graph for UI
    POST /analyze                 — main endpoint: news text → impact graph
    GET  /validate?node_id=...    — on-demand event study for one node

CORS is enabled for the Vite dev server (port 5173).
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from datetime import datetime, timezone

from app.schemas import (
    AnalyzeRequest,
    Edge,
    EdgeStatus,
    ExtractedEvent,
    ImpactGraph,
    Lag,
    LiveNewsResponse,
    NewsFeedItem,
    Node,
    SeedEdge,
    SeedGraphResponse,
    Sign,
    UncertaintyNote,
    URLFetchRequest,
    URLFetchResponse,
    ValidationResult,
    LiveQuoteResult,
    BatchQuotesRequest,
    BatchQuotesResponse,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        from app.marketaux import start_marketaux_background_worker
        start_marketaux_background_worker()
    except Exception as e:
        logger.warning(f"Could not start Marketaux worker: {e}")

    try:
        from app.extraction import extract_event
        demo_texts = [
            "Brent crude surges 12% after Middle East supply disruption",
            "RBI hikes repo rate by 25 bps to curb inflation",
            "Rupee falls sharply against the dollar",
            "OPEC+ Surprise 1.16M bpd Production Cut",
            "CPI inflation surges to 6.83% in August breaching tolerance band",
        ]
        for dt in demo_texts:
            extract_event(dt, demo_mode=True)
        logger.info("[Demo Cache] Pre-warmed extraction cache for %d demo samples.", len(demo_texts))
    except Exception as e:
        logger.warning(f"Could not pre-warm demo cache: {e}")
    yield

# ─── App ──────────────────────────────────────────────────────────────────────

app = FastAPI(
    title       = "Market Impact Graph API",
    description = (
        "Extracts financial events from news and propagates their impact through "
        "a curated causal graph of the Indian economy. "
        "ALL outputs are plausible scenarios — NOT guaranteed predictions."
    ),
    version="0.8.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins     = ["*"],
    allow_credentials = True,
    allow_methods     = ["*"],
    allow_headers     = ["*"],
)


# ─── Health ───────────────────────────────────────────────────────────────────

@app.get("/health", tags=["meta"])
def health() -> dict:
    """Liveness check."""
    return {"status": "ok", "version": app.version}


# ─── Seed graph ───────────────────────────────────────────────────────────────

@app.get("/seed-graph", response_model=SeedGraphResponse, tags=["graph"])
def get_seed_graph() -> SeedGraphResponse:
    """Return the full curated seed graph (nodes + edges) for the frontend."""
    from app.graph_loader import load_seed_graph

    sg = load_seed_graph()
    return SeedGraphResponse(
        node_count = len(sg.nodes),
        edge_count = len(sg.edges),
        nodes      = list(sg.nodes.values()),
        edges      = list(sg.edges.values()),
        themes     = [
            "1. Crude Oil → OMCs, Aviation, Paints, Logistics",
            "2. Inflation → RBI Rate Expectations → Repo Rate",
            "3. Interest Rates → Banks, Real Estate, Auto, Credit",
            "4. INR (USD/INR) → Importers vs Exporters",
            "5. Global Events → FPI Flows → Indian Markets",
        ],
    )


# ─── Analyze ──────────────────────────────────────────────────────────────────

@app.post("/analyze", response_model=ImpactGraph, tags=["analysis"])
def analyze(req: AnalyzeRequest) -> ImpactGraph:
    """
    Main pipeline:
      1. Extract event from news text (LLM × 3 runs for self-consistency).
      2. Propagate through seed graph (signed, decayed BFS).
      3. Run yfinance event study if event_date provided.
      4. Compute confidence scores.
      5. Return ImpactGraph with uncertainty note.
    """
    t0 = time.perf_counter()

    from app.persistence import (
        store_article_idempotent,
        store_analysis_record,
        persist_impact_and_knowledge_graph,
        compute_content_hash,
    )

    now_iso = datetime.now(timezone.utc).isoformat()
    content_hash = compute_content_hash(req.news_text)
    article_id, is_new_article = store_article_idempotent(
        title=req.news_text[:120],
        content=req.news_text,
        publisher="Market News",
        published_at=now_iso,
    )

    # ── Phase P1: Market Relevance Gating ─────────────────────────────────────
    t_start_rel = time.perf_counter()
    from app.news_feed import check_market_relevance
    is_rel, rel_reason, rel_score, rel_entities = check_market_relevance(req.news_text)
    t_rel = (time.perf_counter() - t_start_rel) * 1000

    if not is_rel and not req.demo_mode:
        t_total = (time.perf_counter() - t0) * 1000
        logger.info("[Stage Timings] Gated non-market event in %.1fms (relevance=%.1fms)", t_total, t_rel)
        store_analysis_record(
            article_id=article_id,
            content_hash=content_hash,
            model_version="relevance_gate_v1",
            is_relevant=False,
            relevance_reason=rel_reason,
            sentiment="neutral",
            extracted_entities=[],
            extracted_event={"event_type": "No clear market impact"},
            confidence=0.0,
            status="completed",
        )
        return ImpactGraph(
            nodes            = [],
            edges            = [],
            event            = ExtractedEvent(
                event_type        = "No clear market impact",
                entities          = [],
                direction         = Sign.ambiguous,
                magnitude         = None,
                region            = "India",
                evidence_sentence = req.news_text[:200],
                primary_node      = "unknown",
                unlinked_entities = [],
            ),
            top_paths        = [],
            affected_assets  = [],
            validation       = [],
            uncertainty_note = UncertaintyNote(
                headline = "No Clear Market Impact",
                details  = [rel_reason],
            ),
            agreement_ratio  = 1.0,
            cached           = False,
            is_relevant      = False,
            relevance_reason = rel_reason,
            disclaimer       = "No market transmission channels detected in the input text.",
            mode             = "gated",
        )

    # ── STEP 3: Extraction ────────────────────────────────────────────────────
    t_start_ext = time.perf_counter()
    try:
        from app.extraction import extract_event
        event, agreement_ratio = extract_event(req.news_text, demo_mode=req.demo_mode)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        logger.exception("Extraction failed")
        raise HTTPException(status_code=500, detail=f"Extraction error: {exc}")
    t_ext = (time.perf_counter() - t_start_ext) * 1000

    # ── STEP 4: Propagation ───────────────────────────────────────────────────
    t_start_prop = time.perf_counter()
    from app.propagation import propagate
    top_paths, affected_assets = propagate(event)
    t_prop = (time.perf_counter() - t_start_prop) * 1000

    # ── STEP 6: Market validation (optional) ──────────────────────────────────
    t_start_val = time.perf_counter()
    validation_results: list[ValidationResult] = []
    market_support_map: dict[str, float] = {}
    if req.event_date:
        try:
            from app.validation import run_validation_for_assets
            validation_results, market_support_map = run_validation_for_assets(
                affected_assets, req.event_date
            )
        except Exception as exc:
            logger.warning("Validation failed (non-fatal): %s", exc)
    t_val = (time.perf_counter() - t_start_val) * 1000

    t_start_conf = time.perf_counter()

    # ── STEP 5: Confidence ────────────────────────────────────────────────────
    from app.graph_loader import load_seed_graph
    from app.confidence import enrich_edges_with_confidence, compute_uncertainty_note

    sg       = load_seed_graph()
    seed_ids = set(sg.edges.keys())

    # Build the enriched edges list for the response
    # Include seed graph edges that are on propagated paths + any inferred ones
    response_edge_ids: set[str] = set()
    for path in top_paths:
        response_edge_ids.update(path.edge_ids)

    response_edges: list[Edge] = []
    for eid in response_edge_ids:
        if eid in sg.edges:
            se = sg.edges[eid]
            lo, hi = se.strength_range
            response_edges.append(Edge(
                id           = se.id,
                source       = se.source,
                target       = se.target,
                sign         = se.sign,
                strength_min = lo,
                strength_max = hi,
                lag          = se.lag,
                reasoning    = se.reasoning,
                evidence     = None,  # enriched below if entity matches
                status       = EdgeStatus.seed,
                confidence   = 0.0,  # filled by enrich_edges_with_confidence
                source_ref   = se.source_ref,
            ))

    from app.explanation_engine import SECTOR_PERSPECTIVES, get_entity_perspective

    shock_source = getattr(event, "shock_source", "unclear") or "unclear"

    # Attach evidence sentences and full explanation reasoning to each edge
    for edge in response_edges:
        edge_dir = "positive" if edge.sign == Sign.positive else ("negative" if edge.sign == Sign.negative else "mixed")
        edge.direction = edge_dir
        edge.mechanism_chain = [event.primary_node, edge.source, edge.target]
        edge.hop_explanations = [
            f"Primary trigger {event.primary_node} drives shift in {edge.source}.",
            edge.reasoning or f"Transmission channel from {edge.source} to {edge.target} holds under economic dynamics."
        ]
        # Verify evidence exists verbatim in the news text
        ev_cand = event.evidence_sentence or ""
        verified_ev = ev_cand if (ev_cand and ev_cand.lower() in req.news_text.lower()) else "not provided"

        if edge.source == event.primary_node:
            edge.evidence = verified_ev
            edge.status = EdgeStatus.observed
            edge.claim_type = getattr(event, "claim_type", "verified_news_fact") or "verified_news_fact"
        else:
            edge.evidence = verified_ev if (verified_ev != "not provided" and (edge.source.lower() in verified_ev.lower() or edge.target.lower() in verified_ev.lower())) else "not provided"
            edge.status = EdgeStatus.inferred
            edge.claim_type = "established_mechanism"

        from app.explanation_engine import get_entity_perspective
        target_persp = get_entity_perspective(edge.target, event, edge.mechanism_chain, edge_dir)
        edge.bull_case = target_persp.get("bull", getattr(event, "bull_case", "not provided") or "not provided")
        edge.bear_case = target_persp.get("bear", getattr(event, "bear_case", "not provided") or "not provided")
        edge.reversal_factors = target_persp.get("reversal", getattr(event, "reversal_factors", "not provided") or "not provided")
        edge.assumptions = target_persp.get("assumptions", getattr(event, "assumptions", "not provided") or "not provided")
        edge.shock_source = shock_source
        edge.time_horizon = "immediate" if edge.lag == Lag.immediate else ("short" if edge.lag == Lag.short else "long")

    # Compute sector matrix first so curated matrix support is available for confidence
    t_start_sec = time.perf_counter()
    from app.sector_matrix import compute_dynamic_sector_matrix
    sector_matrix = compute_dynamic_sector_matrix(
        req.news_text, event, affected_assets
    )
    matrix_sector_map: dict[str, float] = {}
    if sector_matrix:
        for s in (sector_matrix.positive_sectors + sector_matrix.negative_sectors + sector_matrix.mixed_sectors):
            matrix_sector_map[s.sector_name.lower().replace(" ", "_")] = s.confidence

    response_edges = enrich_edges_with_confidence(
        response_edges,
        agreement_ratio,
        primary_node=event.primary_node,
        news_text=req.news_text,
        matrix_sector_map=matrix_sector_map,
        market_support_map=market_support_map,
    )

    # Enrich affected_assets with full explanations
    for asset in affected_assets:
        asset_dir = "positive" if asset.direction == Sign.positive else ("negative" if asset.direction == Sign.negative else "mixed")
        a_persp = get_entity_perspective(asset.label or asset.node_id, event, [event.primary_node, asset.node_id], asset_dir)
        asset.direction_label = asset_dir
        asset.mechanism_chain = [event.primary_node, asset.node_id]
        asset.hop_explanations = [
            f"Event triggers macroeconomic shock at {event.primary_node}.",
            asset.reasoning or f"Curated causal transmission link to {asset.label or asset.node_id}."
        ]
        asset.evidence = event.evidence_sentence or "not provided"
        asset.bull_case = a_persp.get("bull", getattr(event, "bull_case", "not provided") or "not provided")
        asset.bear_case = a_persp.get("bear", getattr(event, "bear_case", "not provided") or "not provided")
        asset.reversal_factors = a_persp.get("reversal", getattr(event, "reversal_factors", "not provided") or "not provided")
        asset.shock_source = shock_source
        asset.time_horizon = "short"
        asset.assumptions = a_persp.get("assumptions", getattr(event, "assumptions", "not provided") or "not provided")
        asset.claim_type = "verified_news_fact" if asset.node_id == event.primary_node else "established_mechanism"
        conf_pct = round(asset.confidence * 100)
        conf_tier = "High" if conf_pct >= 75 else ("Medium" if conf_pct >= 50 else "Low")
        asset.confidence_label = f"{conf_tier} ({conf_pct}%)"
        asset.confidence_breakdown = {
            "agreement_ratio": round(agreement_ratio, 2),
            "path_confidence": round(asset.confidence, 2),
        }

    # ── Collect all referenced nodes ──────────────────────────────────────────
    used_node_ids: set[str] = set()
    for edge in response_edges:
        used_node_ids.add(edge.source)
        used_node_ids.add(edge.target)
    # Add the event node itself
    if not event.primary_node.startswith("UNLINKED"):
        used_node_ids.add(event.primary_node)

    response_nodes: list[Node] = [
        sg.nodes[nid] for nid in used_node_ids if nid in sg.nodes
    ]

    # ── Uncertainty note ──────────────────────────────────────────────────────
    inferred_count = sum(1 for e in response_edges if e.status == EdgeStatus.inferred)
    note_dict = compute_uncertainty_note(
        consistency    = agreement_ratio,
        unlinked_count = len(event.unlinked_entities),
        inferred_count = inferred_count,
    )
    uncertainty_note = UncertaintyNote(**note_dict)

    elapsed = round(time.perf_counter() - t0, 2)
    logger.info(
        "Analyze complete in %.2fs: %d nodes, %d edges, %d paths, %d assets",
        elapsed, len(response_nodes), len(response_edges),
        len(top_paths), len(affected_assets),
    )

    t_conf = (time.perf_counter() - t_start_conf) * 1000

    # ── STEP 7: Enrich Sector Exposure Matrix ─────────────────────────────────
    t_start_sec = time.perf_counter()

    if sector_matrix:
        for s_list in [sector_matrix.positive_sectors, sector_matrix.negative_sectors, sector_matrix.mixed_sectors, sector_matrix.neutral_sectors]:
            for s_item in s_list:
                s_item.direction = s_item.impact_category
                driver_name = s_item.active_drivers[0] if s_item.active_drivers else "MacroDriver"
                s_item.mechanism_chain = [event.primary_node, driver_name, s_item.sector_name]
                s_persp = get_entity_perspective(s_item.sector_name, event, s_item.mechanism_chain, s_item.direction)
                s_item.hop_explanations = [
                    f"Macroeconomic shock affects {event.primary_node}.",
                    s_item.transmission_mechanism or f"Direct sensitivity exposure channel to {s_item.sector_name}."
                ]
                s_item.evidence = event.evidence_sentence or "not provided"
                s_item.bull_case = s_persp.get("bull", getattr(event, "bull_case", "not provided") or "not provided")
                s_item.bear_case = s_persp.get("bear", getattr(event, "bear_case", "not provided") or "not provided")
                s_item.reversal_factors = s_persp.get("reversal", getattr(event, "reversal_factors", "not provided") or "not provided")
                s_item.shock_source = shock_source
                s_item.time_horizon = "short"
                s_item.assumptions = s_persp.get("assumptions", getattr(event, "assumptions", "not provided") or "not provided")
                s_item.claim_type = "established_mechanism"
                s_conf_pct = round(s_item.confidence * 100)
                s_conf_tier = "High" if s_conf_pct >= 75 else ("Medium" if s_conf_pct >= 50 else "Low")
                s_item.confidence_label = f"{s_conf_tier} ({s_conf_pct}%)"
                s_item.confidence_breakdown = {
                    "agreement_ratio": round(agreement_ratio, 2),
                    "net_score": round(s_item.net_score, 2),
                    "sector_confidence": round(s_item.confidence, 2),
                }
    t_sec = (time.perf_counter() - t_start_sec) * 1000

    # ── STEP 8: Phase P3 Constituent-Level Stock Intelligence ─────────────────
    t_start_stk = time.perf_counter()
    from app.stock_intelligence import evaluate_constituent_exposures
    stock_intel = evaluate_constituent_exposures(
        req.news_text, event, sector_matrix
    )
    t_stk = (time.perf_counter() - t_start_stk) * 1000

    pos_cnt = sum(1 for a in affected_assets if a.direction == Sign.positive)
    neg_cnt = sum(1 for a in affected_assets if a.direction == Sign.negative)
    avg_conf = sum(p.path_score for p in top_paths) / max(1, len(top_paths)) if top_paths else 0.5
    start_sign = 1 if event.direction == Sign.positive else (-1 if event.direction == Sign.negative else 0)

    # ── STEP 9: Phase P4 Live Market Data Quotes ─────────────────────────────
    t_start_quotes = time.perf_counter()
    live_quotes = {}
    try:
        from app.market_data import fetch_quotes_for_active_entities
        live_quotes = fetch_quotes_for_active_entities(
            response_nodes, affected_assets, stock_intel, demo_mode=req.demo_mode
        )
    except Exception as exc:
        logger.warning("Failed to fetch live quotes (non-fatal): %s", exc)
    t_quotes = (time.perf_counter() - t_start_quotes) * 1000

    # ── STEP 10: Multi-Perspective Detailed Explanation Report ───────────────
    t_start_expl = time.perf_counter()
    detailed_explanation = None
    try:
        from app.explanation_engine import generate_detailed_explanation_report
        detailed_explanation = generate_detailed_explanation_report(
            event, affected_assets, top_paths, agreement_ratio, relevance_score=rel_score if is_rel else 0.85
        )
    except Exception as exc:
        logger.warning("Failed to generate detailed explanation (non-fatal): %s", exc)
    t_expl = (time.perf_counter() - t_start_expl) * 1000

    # ── STEP 11: Capability 4 Cumulative Knowledge Graph Merge ───────────────
    t_start_kg = time.perf_counter()
    kg_update = None
    try:
        from app.knowledge_graph import merge_analysis_into_kg
        kg_update = merge_analysis_into_kg(
            event=event,
            response_nodes=response_nodes,
            response_edges=response_edges,
            news_text=req.news_text,
            source="Market Analysis",
            published_at=datetime.now(timezone.utc).isoformat(),
        )
    except Exception as exc:
        logger.warning("Failed to merge analysis into persistent KG (non-fatal): %s", exc)
    t_kg = (time.perf_counter() - t_start_kg) * 1000

    # ── STEP 12: Dual Persistence (Impact Graph, Articles, Evidence) ─────────
    try:
        from app.persistence import store_analysis_record, persist_impact_and_knowledge_graph
        sentiment_val = "positive" if event.direction == Sign.positive else ("negative" if event.direction == Sign.negative else "neutral")
        ent_list = [getattr(e, "name", str(e)) for e in (event.entities or [])]
        ev_dict = {
            "event_type": getattr(event, "event_type", "Macro Shock"),
            "primary_node": getattr(event, "primary_node", "unknown"),
            "direction": str(getattr(event.direction, "value", event.direction)),
            "magnitude": getattr(event, "magnitude", None),
            "region": getattr(event, "region", "India"),
            "evidence_sentence": getattr(event, "evidence_sentence", ""),
        }
        analysis_id = store_analysis_record(
            article_id=article_id,
            content_hash=content_hash,
            model_version="marketpulse_v1",
            is_relevant=True,
            relevance_reason="Market relevance confirmed",
            sentiment=sentiment_val,
            extracted_entities=ent_list,
            extracted_event=ev_dict,
            confidence=avg_conf,
            status="completed",
        )
        persist_impact_and_knowledge_graph(
            article_id=article_id,
            analysis_id=analysis_id,
            event=event,
            impact_nodes=response_nodes,
            impact_edges=response_edges,
            top_paths=top_paths,
            affected_assets=affected_assets,
            news_text=req.news_text,
            demo_mode=req.demo_mode,
        )
    except Exception as exc:
        logger.warning("Failed to persist impact graph into SQLite (non-fatal): %s", exc)

    t_total = (time.perf_counter() - t0) * 1000
    logger.info(
        "[Stage Timings] /analyze total=%.1fms | relevance=%.1fms, extraction=%.1fms, propagation=%.1fms, validation=%.1fms, confidence=%.1fms, sector_matrix=%.1fms, stock_intel=%.1fms, quotes=%.1fms, explanation=%.1fms, kg=%.1fms",
        t_total, t_rel, t_ext, t_prop, t_val, t_conf, t_sec, t_stk, t_quotes, t_expl, t_kg,
    )

    return ImpactGraph(
        nodes                = response_nodes,
        edges                = response_edges,
        event                = event,
        top_paths            = top_paths,
        affected_assets      = affected_assets,
        validation           = validation_results,
        uncertainty_note     = uncertainty_note,
        agreement_ratio      = agreement_ratio,
        cached               = False,
        start_node           = event.primary_node,
        start_sign           = start_sign,
        kpis                 = {
            "positive": pos_cnt,
            "negative": neg_cnt,
            "avg_confidence": round(avg_conf, 2),
            "chains_traced": len(top_paths),
        },
        graph_size           = {
            "nodes": len(response_nodes),
            "edges": len(response_edges),
            "events": 1,
        },
        disclaimer           = "These are plausible impact chains based on curated economic rules, not predictions.",
        mode                 = "llm" if not req.demo_mode else "fallback",
        sector_matrix        = sector_matrix,
        stock_intelligence   = stock_intel,
        live_quotes          = live_quotes,
        detailed_explanation = detailed_explanation,
        kg_update            = kg_update,
    )


# ─── Phase P4 Market Quote Endpoints ──────────────────────────────────────────

@app.get("/market/quote", response_model=LiveQuoteResult, tags=["market"])
def get_quote(ticker: str = Query(..., description="Ticker symbol, e.g. INDIGO.NS, ^NSEBANK, BZ=F")) -> LiveQuoteResult:
    """Retrieve live or delayed market quote with cache and dual provider fallback."""
    from app.market_data import get_live_quote
    return get_live_quote(ticker)


@app.post("/market/batch-quotes", response_model=BatchQuotesResponse, tags=["market"])
def get_batch(req: BatchQuotesRequest) -> BatchQuotesResponse:
    """Batch fetch market quotes for given tickers."""
    from app.market_data import get_batch_quotes, _get_utc_iso
    quotes = get_batch_quotes(req.tickers)
    return BatchQuotesResponse(
        quotes       = quotes,
        fetched_at   = _get_utc_iso(),
        active_count = len(quotes),
    )


# ─── On-demand validation ─────────────────────────────────────────────────────

@app.get("/validate", response_model=ValidationResult, tags=["analysis"])
def validate_edge(
    node_id:         str   = Query(..., description="Seed graph node id"),
    event_date:      str   = Query(..., description="ISO date YYYY-MM-DD"),
    predicted_sign:  str   = Query("+",  description="'+', '-', or '?'"),
) -> ValidationResult:
    """
    Run a one-off market-model event study for a single node.
    Useful for the frontend 'mini chart' panel.
    """
    from app.validation import run_event_study

    try:
        sign = Sign(predicted_sign)
    except ValueError:
        raise HTTPException(status_code=422, detail="predicted_sign must be '+', '-', or '?'")

    return run_event_study(node_id=node_id, event_date=event_date, predicted_dir=sign)


# ─── Dynamic News Feed Endpoints (Phase P1) ──────────────────────────────────

@app.get("/news/live", response_model=LiveNewsResponse, tags=["news"])
def get_live_news(limit: int = Query(20, ge=1, le=50)) -> LiveNewsResponse:
    """Retrieve live Indian financial market headlines ranked by relevance."""
    from app.news_feed import get_live_news_feed
    items = get_live_news_feed(limit=limit)
    return LiveNewsResponse(
        count         = len(items),
        items         = [NewsFeedItem(**item.__dict__) for item in items],
        source_status = "live",
        last_updated  = datetime.now(timezone.utc).isoformat(),
    )




@app.get("/api/news/suggested", tags=["news"])
@app.get("/news/suggested", tags=["news"])
def get_suggested_news(limit: int = Query(20, ge=1, le=100)) -> dict:
    """
    Marketaux live news suggested endpoint (cached in-memory, refreshed every ~20 min).
    Returns { count, items, meta: { status, fetched_at, total_cached }, source: "Marketaux" }.
    """
    from app.marketaux import get_cached_suggested_news
    res = get_cached_suggested_news()
    items = res.get("items", [])[:limit]
    return {
        "count": len(items),
        "items": items,
        "meta": res.get("meta", {}),
        "source": "Marketaux",
    }


@app.post("/api/news/refresh", tags=["news"])
@app.post("/news/refresh", tags=["news"])
def refresh_news() -> dict:
    """Trigger on-demand Marketaux refresh respecting rate limits."""
    from app.marketaux import fetch_marketaux_news
    items, meta = fetch_marketaux_news(force=True)
    return {
        "count": len(items),
        "items": items[:20],
        "meta": meta,
        "source": "Marketaux",
    }


@app.get("/news/search", response_model=LiveNewsResponse, tags=["news"])
def search_news(q: str = Query(..., min_length=1)) -> LiveNewsResponse:
    """Typeahead search across live cached headlines and topics."""
    from app.news_feed import search_news_feed
    items = search_news_feed(query=q, limit=10)
    return LiveNewsResponse(
        count         = len(items),
        items         = [NewsFeedItem(**item.__dict__) for item in items],
        source_status = "search",
        last_updated  = datetime.now(timezone.utc).isoformat(),
    )


@app.post("/news/fetch-url", response_model=URLFetchResponse, tags=["news"])
def fetch_url(req: URLFetchRequest) -> URLFetchResponse:
    """Safely fetch and clean text from an article URL with relevance gating."""
    from app.news_feed import fetch_url_content, check_market_relevance
    title, text, err = fetch_url_content(req.url)
    if err:
        return URLFetchResponse(
            url              = req.url,
            title            = title,
            text             = "",
            error            = err,
            is_relevant      = False,
            relevance_reason = err,
        )

    is_rel, reason, _, _ = check_market_relevance(f"{title}. {text}")
    return URLFetchResponse(
        url              = req.url,
        title            = title,
        text             = text,
        error            = None,
        is_relevant      = is_rel,
        relevance_reason = reason,
    )


# ─── Capability 4: Persistent Cumulative Knowledge Graph Endpoints ───────────

@app.get("/knowledge-graph", tags=["knowledge_graph"])
def get_knowledge_graph(
    node_type: Optional[str] = Query(None, description="Filter by node type (commodity, sector, indicator, instrument, company, policy)"),
    min_confidence: float = Query(0.0, ge=0.0, le=1.0, description="Minimum edge confidence"),
    start_date: Optional[str] = Query(None, description="Filter edges seen since ISO date"),
    event_id: Optional[str] = Query(None, description="Isolate to specific event's subgraph"),
) -> dict:
    """Retrieve cumulative knowledge graph filtered by node type, minimum confidence, or event subgraph."""
    from app.knowledge_graph import get_cumulative_kg
    return get_cumulative_kg(
        node_type=node_type,
        min_confidence=min_confidence,
        start_date=start_date,
        event_id=event_id,
    )


@app.get("/knowledge-graph/history", tags=["knowledge_graph"])
def get_knowledge_graph_history(
    limit: int = Query(15, ge=1, le=100, description="Number of recent updates to retrieve")
) -> list[dict]:
    """Retrieve audit history of knowledge graph updates from past news analyses."""
    from app.knowledge_graph import get_kg_update_history
    return get_kg_update_history(limit=limit)


@app.post("/knowledge-graph/reset", tags=["knowledge_graph"])
def reset_knowledge_graph() -> dict:
    """Reseed cumulative knowledge graph from canonical seed graph."""
    from app.knowledge_graph import init_kg_db
    init_kg_db(force_reseed=True)
    return {"status": "ok", "message": "Knowledge graph reset to canonical seed state."}


# ─── Dual Persistence & Connected Graph Endpoints ────────────────────────────

@app.get("/api/impact-graph", tags=["impact_graph"])
@app.get("/impact-graph/latest", tags=["impact_graph"])
def get_impact_graph_endpoint(event_id: Optional[str] = Query(None, description="Event ID or latest")) -> dict:
    """Retrieve connected, persistent Impact Graph from SQLite database."""
    from app.persistence import get_persisted_impact_graph
    return get_persisted_impact_graph(event_id=event_id)


@app.get("/api/impact-graph/{event_id}", tags=["impact_graph"])
def get_impact_graph_by_id(event_id: str) -> dict:
    """Retrieve specific persisted Impact Graph by event ID."""
    from app.persistence import get_persisted_impact_graph
    data = get_persisted_impact_graph(event_id=event_id)
    if not data or not data.get("event"):
        raise HTTPException(status_code=404, detail=f"Impact event '{event_id}' not found.")
    return data


@app.get("/api/entity/{entity_id}", tags=["impact_graph"])
def get_entity_endpoint(entity_id: str) -> dict:
    """Retrieve entity details, mention count, and connected edges from SQLite."""
    from app.persistence import get_entity_profile
    profile = get_entity_profile(entity_id)
    if not profile:
        raise HTTPException(status_code=404, detail=f"Entity '{entity_id}' not found.")
    return profile


@app.get("/api/edge/{edge_id:path}/evidence", tags=["impact_graph"])
def get_edge_evidence_endpoint(edge_id: str) -> dict:
    """Retrieve evidence chain, quotes, source article, and conflict status for an edge."""
    from app.persistence import get_edge_evidence_details
    details = get_edge_evidence_details(edge_id)
    if not details:
        raise HTTPException(status_code=404, detail=f"Edge '{edge_id}' not found.")
    return details


@app.get("/api/articles", tags=["news"])
def get_articles_endpoint(limit: int = Query(25, ge=1, le=100)) -> list[dict]:
    """Retrieve ingested news articles, status, and associated analysis runs."""
    from app.persistence import get_all_persisted_articles
    return get_all_persisted_articles(limit=limit)


