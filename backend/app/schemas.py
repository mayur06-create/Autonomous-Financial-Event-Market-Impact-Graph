"""
schemas.py — Pydantic v2 data models for Market Impact Graph.  STEP 1.

All domain types live here; other modules import from this file only.
Convention for 'inr' node: value = USD/INR spot rate (higher = weaker rupee).
"""

from __future__ import annotations
from enum import Enum
from typing import Optional, Any
from pydantic import BaseModel, Field, model_validator


# ─── Enumerations ─────────────────────────────────────────────────────────────

class Sign(str, Enum):
    positive  = "+"
    negative  = "-"
    ambiguous = "?"


class EdgeStatus(str, Enum):
    """
    observed : the causal link is directly stated in the news article.
    seed     : exists in our curated causal graph with published evidence.
    inferred : LLM proposed it but it is NOT in the seed graph → low confidence.
    """
    observed = "observed"
    seed     = "seed"
    inferred = "inferred"


class Lag(str, Enum):
    """Approximate time for effect to materialize after trigger."""
    immediate = "immediate"   # same trading session to 24 h
    short     = "short"       # days to ~4 weeks
    medium    = "medium"      # 1–3 months
    long      = "long"        # 1–3 quarters


class NodeType(str, Enum):
    event      = "event"        # triggering news event (transient node)
    commodity  = "commodity"    # crude oil, gold, ATF …
    company    = "company"      # specific listed entity
    sector     = "sector"       # NSE sectoral index / group
    indicator  = "indicator"    # macro variable (CPI, CAD, FPI flows …)
    instrument = "instrument"   # financial instrument (Nifty, G-sec yield …)
    policy     = "policy"       # central bank / government action


# ─── Graph primitives ─────────────────────────────────────────────────────────

class Node(BaseModel):
    id:          str
    label:       str
    type:        NodeType
    description: Optional[str] = None
    ticker:      Optional[str] = None   # yfinance ticker for validation


class SeedEdge(BaseModel):
    """Raw form of one edge in seed_graph.json — validated on load."""
    id:             str
    source:         str
    target:         str
    sign:           Sign
    strength_range: list[float] = Field(min_length=2, max_length=2)
    lag:            Lag
    reasoning:      str
    source_ref:     str

    @model_validator(mode="after")
    def check_range(self) -> "SeedEdge":
        lo, hi = self.strength_range
        if not (0.0 <= lo <= hi <= 1.0):
            raise ValueError(
                f"Edge {self.id}: strength_range [{lo},{hi}] must satisfy "
                "0 ≤ lo ≤ hi ≤ 1"
            )
        return self


class EventArchetype(str, Enum):
    macro_shock               = "macro_shock"
    policy_regulation         = "policy_regulation"
    company_earnings_outlook  = "company_earnings_outlook"
    sector_outlook            = "sector_outlook"
    market_commentary         = "market_commentary"
    irrelevant                = "irrelevant"


class RelationType(str, Enum):
    increases       = "increases"
    decreases       = "decreases"
    pressures       = "pressures"
    benefits        = "benefits"
    correlates_with = "correlates_with"
    member_of       = "member_of"
    exposed_to      = "exposed_to"


class ClaimType(str, Enum):
    verified_news_fact      = "verified_news_fact"
    established_mechanism   = "established_mechanism"
    historical_association  = "historical_association"
    ai_inferred             = "ai_inferred"
    unverified              = "unverified"


class TypedEntity(BaseModel):
    """Extracted entity with canonical linking and verified evidence span."""
    id:            str
    name:          str
    entity_type:   str   # company | commodity | sector | indicator | instrument
    canonical_id:  Optional[str] = None
    is_linked:     bool = True
    evidence_span: str   # verbatim substring from the article text


class Edge(BaseModel):
    """Enriched edge returned in the API response."""
    id:                   str
    source:               str
    target:               str
    sign:                 Sign
    strength_min:         float = Field(ge=0.0, le=1.0)
    strength_max:         float = Field(ge=0.0, le=1.0)
    lag:                  Lag
    reasoning:            str
    evidence:             Optional[str] = "not provided"   # verbatim sentence from the news or "not provided"
    status:               EdgeStatus
    confidence:           float = Field(ge=0.0, le=1.0)
    source_ref:           str
    direction:            str = "mixed"  # positive / negative / mixed / neutral
    relation:             str = "exposed_to" # increases | decreases | pressures | benefits | correlates_with | member_of | exposed_to
    mechanism_chain:      list[str] = Field(default_factory=list) # step-by-step: event -> driver -> sector or asset
    hop_explanations:     list[str] = Field(default_factory=list) # one sentence per hop explaining why the hop holds
    bull_case:            str = "not provided"  # why it could rise
    bear_case:            str = "not provided"  # why it could fall
    reversal_factors:     str = "not provided"  # what could reverse it
    shock_source:         str = "unclear"       # supply / demand / risk / unclear
    time_horizon:         str = "short"         # immediate / short / long
    assumptions:          str = "not provided"
    claim_type:           str = "established_mechanism" # verified_news_fact / established_mechanism / historical_association / ai_inferred / unverified
    confidence_label:     str = "Medium (50%)"
    confidence_breakdown: dict[str, Any] = Field(default_factory=dict)


# ─── LLM extraction output ───────────────────────────────────────────────────

class ExtractedEvent(BaseModel):
    """Structured event extracted from the news article — LLM output."""
    event_type:        str
    archetype:         str = "macro_shock" # macro_shock | policy_regulation | company_earnings_outlook | sector_outlook | market_commentary | irrelevant
    entities:          list[str]
    typed_entities:    list[TypedEntity] = Field(default_factory=list)
    direction:         Sign
    magnitude:         Optional[str] = None
    region:            str
    evidence_sentence: str
    # post-processing: linked seed node or "UNLINKED:<original_name>"
    primary_node:      str
    unlinked_entities: list[str] = Field(default_factory=list)
    shock_source:      str = "unclear"  # supply / demand / risk / policy / unclear
    bull_case:         str = "not provided"
    bear_case:         str = "not provided"
    reversal_factors:  str = "not provided"
    time_horizon:      str = "short"
    assumptions:       str = "not provided"
    claim_type:        str = "verified_news_fact"


# ─── Propagation output ──────────────────────────────────────────────────────

class PathResult(BaseModel):
    """One causal path from the event node to a downstream asset."""
    nodes:      list[str]   # node ids in order, source → target
    edge_ids:   list[str]
    path_score: float       # product of midpoint strengths × decay^(hops-1)
    sign:       Sign        # net directional effect on terminal node
    hop_count:  int
    summary:    str         # human-readable one-liner, e.g. "Crude→ATF→Aviation (−)"


class AffectedAsset(BaseModel):
    node_id:              str
    label:                str
    node_type:            NodeType
    direction:            Sign
    confidence:           float
    paths:                int         # number of distinct paths reaching this node
    reasoning:            str
    direction_label:      str = "mixed"
    mechanism_chain:      list[str] = Field(default_factory=list)
    hop_explanations:     list[str] = Field(default_factory=list)
    evidence:             str = "not provided"
    bull_case:            str = "not provided"
    bear_case:            str = "not provided"
    reversal_factors:     str = "not provided"
    shock_source:         str = "unclear"
    time_horizon:         str = "short"
    assumptions:          str = "not provided"
    claim_type:           str = "established_mechanism"
    confidence_label:     str = "Medium (50%)"
    confidence_breakdown: dict[str, Any] = Field(default_factory=dict)


# ─── Confidence breakdown ────────────────────────────────────────────────────

class ConfidenceBreakdown(BaseModel):
    """
    Formula (documented in confidence.py):
      If market_support available:
        confidence = 0.50 × seed_support + 0.30 × consistency + 0.20 × market_support
      Else:
        confidence = 0.60 × seed_support + 0.40 × consistency
    """
    seed_support:   float
    consistency:    float             # agreement ratio across 3 LLM runs
    market_support: Optional[float]   # from event study; None if unavailable
    final:          float
    formula_note:   str


# ─── Validation / event study ────────────────────────────────────────────────

class ValidationResult(BaseModel):
    """
    Indicative event-study result.  The benchmark regression is noisy because
    macro events move the entire market; treat results as qualitative signal only.
    """
    ticker:          str
    node_id:         str
    car:             Optional[float]   # Cumulative Abnormal Return; None on failure
    event_date:      Optional[str]     # ISO date
    window_days:     int
    direction_match: Optional[bool]    # does CAR sign agree with graph prediction?
    label:           str = "indicative"
    note:            str               # always includes benchmark noise caveat


# ─── Top-level API models ────────────────────────────────────────────────────

class UncertaintyNote(BaseModel):
    headline: str
    details:  list[str]


# ─── Phase P2: Event Taxonomy, Macro Drivers & Dynamic Sector Matrix ─────────

class EventTaxonomyCategory(str, Enum):
    monetary_policy             = "monetary_policy"
    fiscal_policy               = "fiscal_policy"
    commodity_shock             = "commodity_shock"
    fx_currency                 = "fx_currency"
    geopolitical_trade          = "geopolitical_trade"
    regulatory_policy           = "regulatory_policy"
    banking_credit              = "banking_credit"
    corporate_earnings          = "corporate_earnings"
    inflation_macro             = "inflation_macro"
    supply_chain_disruption     = "supply_chain_disruption"
    climate_monsoon             = "climate_monsoon"
    domestic_demand_consumption = "domestic_demand_consumption"
    global_spillover            = "global_spillover"
    general_macro               = "general_macro"


class MacroDriver(str, Enum):
    input_cost             = "input_cost"
    demand_volume          = "demand_volume"
    interest_rates         = "interest_rates"
    fx_exposure            = "fx_exposure"
    regulatory_burden      = "regulatory_burden"
    liquidity_availability = "liquidity_availability"
    commodity_pricing      = "commodity_pricing"
    credit_quality         = "credit_quality"
    market_sentiment       = "market_sentiment"


class DriverImpact(BaseModel):
    driver:    MacroDriver
    name:      str
    direction: Sign
    intensity: float = Field(ge=0.0, le=1.0)
    reasoning: str


class SectorExposureItem(BaseModel):
    sector_name:            str
    benchmark_index:        str
    ticker:                 Optional[str] = None
    impact_category:        str  # "positive", "negative", "mixed", "neutral"
    net_score:              float = Field(ge=-1.0, le=1.0)
    confidence:             float = Field(ge=0.0, le=1.0)
    transmission_mechanism: str
    active_drivers:         list[str] = Field(default_factory=list)
    key_beneficiaries:      list[str] = Field(default_factory=list)
    key_pressured:          list[str] = Field(default_factory=list)
    direction:              str = "mixed"  # positive / negative / mixed / neutral
    mechanism_chain:        list[str] = Field(default_factory=list)
    hop_explanations:       list[str] = Field(default_factory=list)
    evidence:               str = "not provided"
    bull_case:              str = "not provided"
    bear_case:              str = "not provided"
    reversal_factors:       str = "not provided"
    shock_source:           str = "unclear"
    time_horizon:           str = "short"
    assumptions:            str = "not provided"
    claim_type:             str = "established_mechanism"
    confidence_label:       str = "Medium (50%)"
    confidence_breakdown:   dict[str, Any] = Field(default_factory=dict)


class DynamicSectorMatrix(BaseModel):
    event_category:       EventTaxonomyCategory
    event_category_label: str
    event_summary:        str
    active_drivers:       list[DriverImpact]
    positive_sectors:     list[SectorExposureItem]
    negative_sectors:     list[SectorExposureItem]
    mixed_sectors:        list[SectorExposureItem]
    neutral_sectors:      list[SectorExposureItem]
    methodology_note:     str


# ─── Phase P3: Constituent-Level Stock Intelligence & Sensitivity ─────────────

class ConstituentExposureItem(BaseModel):
    symbol:                 str  # e.g., "INDIGO", "TCS", "HDFCBANK"
    company_name:           str
    ticker:                 str  # e.g., "INDIGO.NS"
    sector:                 str
    direction:              Sign
    impact_class:           str  # "Key Beneficiary", "High Pressure", "Resilient", "Mixed"
    sensitivity_score:      float = Field(ge=-1.0, le=1.0)
    confidence:             float = Field(ge=0.0, le=1.0)
    transmission_mechanism: str
    key_factors:            dict[str, str] = Field(default_factory=dict)
    cushion_or_hedge:       Optional[str] = None
    historical_beta:        float = 1.0


class StockIntelligenceReport(BaseModel):
    total_stocks_analyzed: int
    top_beneficiaries:     list[ConstituentExposureItem]
    top_pressured:         list[ConstituentExposureItem]
    mixed_or_resilient:    list[ConstituentExposureItem]
    methodology_summary:   str


# ─── Phase P4: Live Market Data & Dual Provider Models ────────────────────────

class LiveQuoteResult(BaseModel):
    ticker:           str
    price:            Optional[float] = None
    change:           Optional[float] = None
    change_pct:       Optional[float] = None
    currency:         str = "INR"
    timestamp:        str
    data_status:      str = "delayed"  # "live", "delayed", "cached", "unavailable", "unconfigured"
    provider:         str = "yfinance" # "yfinance", "alphavantage", "cache", "none"
    high_52w:         Optional[float] = None
    low_52w:          Optional[float] = None
    volume:           Optional[int] = None
    note:             Optional[str] = None


class BatchQuotesRequest(BaseModel):
    tickers: list[str]


class BatchQuotesResponse(BaseModel):
    quotes:       dict[str, LiveQuoteResult]
    fetched_at:   str
    active_count: int


class AnalyzeRequest(BaseModel):
    news_text:  Optional[str] = None
    text:       Optional[str] = None
    url:        Optional[str] = None
    demo_mode:  bool = False
    event_date: Optional[str] = None   # ISO date for validation (YYYY-MM-DD)

    def model_post_init(self, __context: Any) -> None:
        raw = self.news_text or self.text
        if not raw and self.url:
            from app.news_feed import fetch_url_content
            title, fetched_text, err = fetch_url_content(self.url)
            if err:
                raise ValueError(f"Could not load article from URL: {err}")
            raw = f"{title}. {fetched_text}" if title else fetched_text
        if not raw or len(raw.strip()) < 20:
            raise ValueError("news text must be at least 20 characters")
        if not self.news_text:
            self.news_text = raw
        if not self.text:
            self.text = raw


class ExplanationCard(BaseModel):
    entity_name:          str
    entity_type:          str   # "sector" | "company" | "indicator" | "instrument"
    direction:            str   # "positive" | "negative" | "mixed" | "neutral"
    bull_case:            str   # why it could rise
    bear_case:            str   # why it could fall
    mechanism_chain:      list[str] # step-by-step
    evidence_sentence:    str   # verbatim from article
    claim_type:           str   # verified_news_fact | established_mechanism | historical_association | ai_inferred | unverified_or_conflicting
    reversal_factors:     str   # hedging, priced-in, macro shifts
    time_horizon:         str   # "immediate" | "short" | "long"
    key_assumptions:      str
    confidence_label:     str   # e.g. "High (82%)"
    confidence_breakdown: dict[str, float] = Field(default_factory=dict)
    data_freshness:       str   # ISO timestamp


class DetailedExplanationReport(BaseModel):
    event_summary:           str
    event_type:              str
    shock_source:            str   # "supply" | "demand" | "risk" | "policy" | "unclear"
    relevance_score:         float
    article_tone:            str   # "bullish" | "bearish" | "neutral" | "cautious"
    market_impact_direction: str   # "net_positive" | "net_negative" | "mixed" | "neutral"
    tone_vs_impact_note:     str
    overall_confidence:      str   # "high" | "medium" | "low"
    overall_confidence_score: float
    confidence_breakdown:    dict[str, Any] = Field(default_factory=dict)
    likely_positive:         list[ExplanationCard] = Field(default_factory=list)
    likely_negative:         list[ExplanationCard] = Field(default_factory=list)
    mixed_or_unclear:        list[ExplanationCard] = Field(default_factory=list)
    risk_note:               str = "These are plausible economic scenarios based on curated transmission rules — NOT guaranteed predictions or price targets."


class ImpactGraph(BaseModel):
    nodes:                list[Node]
    edges:                list[Edge]
    event:                ExtractedEvent
    top_paths:            list[PathResult]
    affected_assets:      list[AffectedAsset]
    validation:           list[ValidationResult] = Field(default_factory=list)
    uncertainty_note:     UncertaintyNote
    agreement_ratio:      float = Field(ge=0.0, le=1.0)
    cached:               bool = False
    start_node:           Optional[str] = None
    start_sign:           Optional[int] = None
    kpis:                 Optional[dict] = None
    graph_size:           Optional[dict] = None
    disclaimer:           Optional[str] = None
    mode:                 Optional[str] = "llm"
    is_relevant:          bool = True
    relevance_reason:     Optional[str] = None
    sector_matrix:        Optional[DynamicSectorMatrix] = None
    stock_intelligence:   Optional[StockIntelligenceReport] = None
    live_quotes:          Optional[dict[str, LiveQuoteResult]] = None
    detailed_explanation: Optional[DetailedExplanationReport] = None
    kg_update:            Optional[dict[str, Any]] = None


class SeedGraphResponse(BaseModel):
    """Response for GET /seed-graph."""
    node_count: int
    edge_count: int
    nodes:      list[Node]
    edges:      list[SeedEdge]
    themes:     list[str]


# ─── Dynamic News & Feed Models (Phase P1) ───────────────────────────────────

class NewsFeedItem(BaseModel):
    id:               str
    title:            str
    summary:          str
    url:              Optional[str] = None
    source:           str
    published_at:     str
    relevance_score:  float
    is_relevant:      bool
    matched_entities: list[str] = Field(default_factory=list)


class LiveNewsResponse(BaseModel):
    count:         int
    items:         list[NewsFeedItem]
    source_status: str = "live"
    last_updated:  str


class URLFetchRequest(BaseModel):
    url: str


class URLFetchResponse(BaseModel):
    url:              str
    title:            str
    text:             str
    error:            Optional[str] = None
    is_relevant:      Optional[bool] = None
    relevance_reason: Optional[str] = None

