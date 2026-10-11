"""
explanation_engine.py — Detailed Explanation & Multi-Perspective Reasoning Engine (Step 4).

Constructs structured, explainable causal reasoning for every affected sector and asset:
  - Bull and bear cases for each entity (both directions evaluated)
  - Step-by-step transmission chains
  - Verbatim evidence from news
  - Epistemic claim tags (verified_news_fact, established_mechanism, etc.)
  - Reversal factors and key assumptions
  - Transparent, code-computed confidence breakdowns
"""

from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from app.schemas import (
    AffectedAsset,
    DetailedExplanationReport,
    ExplanationCard,
    ExtractedEvent,
    NodeType,
    PathResult,
    Sign,
)

logger = logging.getLogger("market_impact.explanation_engine")

# ── Domain knowledge base for two-sided reasoning & reversal factors ─────────

SECTOR_PERSPECTIVES = {
    "Aviation": {
        "bull": "Lower fuel expenses if crude drops or yields expand on strong passenger travel demand and pricing power.",
        "bear": "Surging ATF fuel expenses (35-40% of OpEx) squeeze operating margins; USD/INR depreciation inflates dollar aircraft leases.",
        "reversal": "Pass-through fuel surcharges to passenger fares, jet fuel price hedging, or capacity discipline across airlines.",
        "assumptions": "ATF price pass-through elasticity remains ~50-70%; passenger load factors hold above 80%.",
    },
    "Upstream Oil & Gas": {
        "bull": "Higher crude oil and gas realizations directly expand upstream top-line revenues and EBITDA cash flows.",
        "bear": "Government windfall tax hikes or global demand destruction if oil stays excessively elevated.",
        "reversal": "Windfall tax adjustments by Ministry of Finance, OPEC output surges, or production declines in aging fields.",
        "assumptions": "Net realized crude price post-windfall tax remains above $70/bbl.",
    },
    "Oil Marketing Cos": {
        "bull": "Stable marketing margins and inventory valuation gains if retail petrol/diesel prices are market-linked.",
        "bear": "Retail price freeze during crude rallies leads to heavy marketing under-recoveries and refining margin compression.",
        "reversal": "Retail pump price hikes by government, crude correction, or refining crack spread expansion.",
        "assumptions": "OMC retail price flexibility is maintained by government policy.",
    },
    "Paints & Chemicals": {
        "bull": "Input cost deflation when crude derivatives (monomers, solvents, TiO2) fall, boosting gross margins.",
        "bear": "Crude derivative cost spikes squeeze gross margins unless offset by aggressive retail price hikes.",
        "reversal": "Timely dealer price hikes, premiumization shift, or substitution with water-based alternative formulations.",
        "assumptions": "Raw material costs comprise 50-55% of revenue; pricing power remains intact against competition.",
    },
    "Banking": {
        "bull": "Credit growth acceleration and asset quality improvement; floating-rate loan books reprice faster than deposits.",
        "bear": "Rising bond yields cause treasury MTM mark-to-market losses; elevated policy rates risk SME/retail loan defaults.",
        "reversal": "RBI liquidity injections, credit cost normalization, or strong CASA deposit franchise cushions.",
        "assumptions": "Net Interest Margins (NIM) remain resilient; NPA slippages stay within historical provisions.",
    },
    "IT Services": {
        "bull": "USD/INR rupee depreciation boosts operating margins (70%+ revenues in USD); US tech modernization capex.",
        "bear": "Global recessionary caution leads to discretionary IT budget cuts, client deal delays, or visa/cost inflation.",
        "reversal": "Long-term cost-takeout mega deals, enterprise AI platform adoption, or cross-currency hedges.",
        "assumptions": "Every 1% INR depreciation translates to ~25-30 bps operating margin expansion.",
    },
    "Auto": {
        "bull": "Commodity cooling (steel, aluminum, plastics) aids gross margins; festive demand and SUV premiumization.",
        "bear": "Rising interest rates increase vehicle financing costs (75%+ vehicles bought on loan); fuel price inflation dampens usage.",
        "reversal": "Festive OEM discounts, EV localization incentives, or commodity hedging programs.",
        "assumptions": "Auto loan interest rates are the primary friction for entry-level two-wheelers and small cars.",
    },
    "Real Estate": {
        "bull": "Strong structural housing demand, luxury segment momentum, and inventory liquidation.",
        "bear": "High mortgage home-loan interest rates increase EMI burden and delay homebuyer buying decisions.",
        "reversal": "Developer subvention schemes, wage growth outstripping rate hikes, or Tier-2 market expansion.",
        "assumptions": "Home loan interest rates stay below the 9.5% affordability threshold.",
    },
    "Pharma": {
        "bull": "US generic pricing stabilization, dollar export realization boost from weak INR, and domestic chronic growth.",
        "bear": "US FDA import alerts/warning letters, price erosion in commoditized generics, or raw API price spikes.",
        "reversal": "First-to-file (FTF) launches, specialty pipeline commercialization, or bio-similar approvals.",
        "assumptions": "Export revenue share exceeds 60%; regulatory compliance at key facilities remains unblemished.",
    },
    "FMCG": {
        "bull": "Rural income recovery, raw material cost deflation (palm oil, crude packaging), and volume growth turnaround.",
        "bear": "Agricultural inflation or crude derivative cost spikes squeeze gross margins and force grammage cuts.",
        "reversal": "Direct-to-consumer premiumization, monsoon recovery, or rural welfare transfers.",
        "assumptions": "Volume growth accelerates with stable retail prices.",
    },
    "Metals": {
        "bull": "Domestic infrastructure capex, global stimulus (e.g. China), and international export price firmness.",
        "bear": "High coking coal and power input costs; cheap import dumping dampens domestic realizations.",
        "reversal": "Government anti-dumping duties, safeguard tariffs, or domestic steel procurement mandates.",
        "assumptions": "Domestic demand remains supported by government highway and railway capex.",
    },
}

GENERIC_PERSPECTIVE = {
    "bull": "Potential operating upside if second-order transmission adjustments improve cash flows.",
    "bear": "Cross-current cost or valuation pressures transmitted across downstream channels.",
    "reversal": "Shifts in underlying commodity drivers, central bank policy adjustments, or currency stabilization.",
    "assumptions": "Curated macroeconomic sensitivity dynamics apply.",
}

def get_entity_perspective(name: str, event: ExtractedEvent, chain_steps: list[str], direction: str) -> dict[str, str]:
    """Generates entity-specific causal reasoning derived from current event variables and transmission chains."""
    if name in SECTOR_PERSPECTIVES:
        return SECTOR_PERSPECTIVES[name]

    trigger = (event.primary_node or "Macro Event").replace("_", " ").title()
    dir_sign = event.direction.value if hasattr(event.direction, 'value') else str(event.direction)
    dir_verb = "rises" if dir_sign == "+" else "softens"
    hops_cnt = max(1, len(chain_steps) - 1)

    if direction == "positive":
        bull_text = f"{name} benefits as {trigger} {dir_verb}, lowering relative input pressure or driving favorable substitution volume."
        bear_text = f"Upside for {name} could face friction if broader macro inflation or monetary tightening dampens consumer demand."
    elif direction == "negative":
        bull_text = f"{name} could mitigate pressure through proactive retail price hikes, inventory hedges, or operational efficiencies."
        bear_text = f"{name} faces margin compression or volume headwinds transmitted via the {trigger} transmission channel."
    else:
        bull_text = f"Selective segments of {name} gain from operational factor advantages tied to {trigger}."
        bear_text = f"Cross-current macro pressures from {trigger} create margin uncertainty for {name}."

    reversal_text = f"Reversal may occur if {trigger} shifts direction, regulatory policy intervenes, or currency dynamics normalize."
    assumptions_text = f"Assumes {hops_cnt}-hop transmission from {trigger} to {name} propagates without immediate structural hedging."

    return {
        "bull": bull_text,
        "bear": bear_text,
        "reversal": reversal_text,
        "assumptions": assumptions_text,
    }


def _determine_shock_source(event: ExtractedEvent) -> str:
    et = (event.event_type or "").lower()
    ev = (event.evidence_sentence or "").lower()
    combined = f"{et} {ev}"

    if any(w in combined for w in ["supply", "opec", "production cut", "embargo", "shortage", "pipeline", "refinery"]):
        return "supply"
    if any(w in combined for w in ["rbi", "repo", "rate", "fed", "monetary", "fiscal", "tax", "budget", "duty", "tariff", "policy"]):
        return "policy"
    if any(w in combined for w in ["demand", "consumption", "gdp", "sales", "spending", "orders"]):
        return "demand"
    if any(w in combined for w in ["war", "conflict", "fii", "outflow", "sanction", "tension", "crisis"]):
        return "risk"
    return "unclear"


def _determine_article_tone(event: ExtractedEvent) -> str:
    direction = str(event.direction.value if hasattr(event.direction, 'value') else event.direction)
    ev = (event.evidence_sentence or "").lower()

    if any(w in ev for w in ["surge", "rally", "boom", "gain", "optimis", "soar", "record"]):
        return "bullish"
    if any(w in ev for w in ["slump", "plunge", "concern", "worry", "drop", "fall", "tumble", "threat"]):
        return "bearish"
    if direction == "+":
        return "bullish"
    elif direction == "-":
        return "bearish"
    return "neutral"


def generate_detailed_explanation_report(
    event: ExtractedEvent,
    affected_assets: list[AffectedAsset],
    top_paths: list[PathResult],
    agreement_ratio: float,
    relevance_score: float = 0.85,
) -> DetailedExplanationReport:
    """
    Builds comprehensive, multi-perspective explanation report with
    per-asset cards grouped by likely direction.
    """
    shock_source = _determine_shock_source(event)
    article_tone = _determine_article_tone(event)

    # Build lookup of paths per target
    target_to_paths: dict[str, list[PathResult]] = {}
    for p in top_paths:
        if p.nodes:
            target = p.nodes[-1]
            target_to_paths.setdefault(target, []).append(p)

    likely_positive: list[ExplanationCard] = []
    likely_negative: list[ExplanationCard] = []
    mixed_or_unclear: list[ExplanationCard] = []

    now_iso = datetime.now(timezone.utc).isoformat()

    for asset in affected_assets:
        name = asset.label or asset.node_id
        direction_str = str(asset.direction.value if hasattr(asset.direction, 'value') else asset.direction)

        if direction_str == "+":
            dir_label = "positive"
        elif direction_str == "-":
            dir_label = "negative"
        else:
            dir_label = "mixed"

        # Mechanism chain
        matching_paths = target_to_paths.get(asset.node_id, [])
        if matching_paths:
            best_path = max(matching_paths, key=lambda p: p.path_score)
            chain_steps = list(best_path.nodes)
        else:
            chain_steps = [event.primary_node, name]

        # Dynamic perspective derived from news event context
        persp = get_entity_perspective(name, event, chain_steps, dir_label)

        # Epistemic Claim Tag
        if asset.node_id == event.primary_node or (event.evidence_sentence and name.lower() in event.evidence_sentence.lower()):
            claim_type = "verified_news_fact"
        elif asset.node_type in {NodeType.sector, NodeType.company} and matching_paths:
            claim_type = "established_mechanism"
        elif agreement_ratio >= 0.8:
            claim_type = "historical_association"
        else:
            claim_type = "ai_inferred"

        # Confidence label
        conf_pct = round(asset.confidence * 100)
        conf_tier = "High" if conf_pct >= 75 else "Medium" if conf_pct >= 50 else "Low"
        conf_label = f"{conf_tier} ({conf_pct}%)"

        conf_breakdown = {
            "llm_agreement": round(agreement_ratio, 2),
            "seed_rule_strength": round(asset.confidence * 0.7, 2),
            "evidence_quality": 0.85 if claim_type == "verified_news_fact" else 0.70,
        }

        # Time horizon
        time_horizon = "immediate" if len(chain_steps) <= 2 else "short" if len(chain_steps) <= 3 else "long"

        card = ExplanationCard(
            entity_name          = name,
            entity_type          = asset.node_type.value if hasattr(asset.node_type, 'value') else str(asset.node_type),
            direction            = dir_label,
            bull_case            = persp.get("bull", "not provided"),
            bear_case            = persp.get("bear", "not provided"),
            mechanism_chain      = chain_steps,
            evidence_sentence    = event.evidence_sentence or "not provided",
            claim_type           = claim_type,
            reversal_factors     = persp.get("reversal", "not provided"),
            time_horizon         = time_horizon,
            key_assumptions      = persp.get("assumptions", "not provided"),
            confidence_label     = conf_label,
            confidence_breakdown = conf_breakdown,
            data_freshness       = now_iso,
        )

        if dir_label == "positive":
            likely_positive.append(card)
        elif dir_label == "negative":
            likely_negative.append(card)
        else:
            mixed_or_unclear.append(card)

    # Net market impact direction
    if len(likely_positive) > len(likely_negative) + 1:
        net_direction = "net_positive"
    elif len(likely_negative) > len(likely_positive) + 1:
        net_direction = "net_negative"
    else:
        net_direction = "mixed"

    # Tone vs impact comparison
    if article_tone == "bullish" and net_direction == "net_negative":
        tone_note = (
            "Article headline expresses bullish/rising momentum on the primary trigger (e.g. commodity surge), "
            "but macroeconomic propagation generates widespread cost pressures and negative net impact across downstream consuming sectors."
        )
    elif article_tone == "bearish" and net_direction == "net_positive":
        tone_note = (
            "Article notes falling variables, but second-order effects (e.g. input-cost deflation or policy easing) "
            "provide net positive tailwinds to domestic sectors."
        )
    else:
        tone_note = "Article tone aligns directionally with downstream economic transmission results."

    overall_conf_score = round(min(1.0, (agreement_ratio * 0.5 + (relevance_score or 0.8) * 0.5)), 2)
    overall_conf_tier = "high" if overall_conf_score >= 0.75 else "medium" if overall_conf_score >= 0.50 else "low"

    event_summary = (
        f"{event.event_type.capitalize()} affecting {event.primary_node} "
        f"({'rising (+)' if str(event.direction) in {'+', 'Sign.positive'} else 'falling (-)'})"
        f"{f' with magnitude {event.magnitude}' if event.magnitude else ''} in {event.region}."
    )

    return DetailedExplanationReport(
        event_summary           = event_summary,
        event_type              = event.event_type or "Financial Market Event",
        shock_source            = shock_source,
        relevance_score         = round(relevance_score, 2),
        article_tone            = article_tone,
        market_impact_direction = net_direction,
        tone_vs_impact_note     = tone_note,
        overall_confidence      = overall_conf_tier,
        overall_confidence_score= overall_conf_score,
        confidence_breakdown    = {
            "consistency_ratio": agreement_ratio,
            "relevance_score": relevance_score,
            "seed_graph_coverage": 1.0,
        },
        likely_positive         = likely_positive,
        likely_negative         = likely_negative,
        mixed_or_unclear        = mixed_or_unclear,
        risk_note               = "These are plausible economic transmission scenarios based on fundamental factor modeling — NOT guaranteed predictions or price targets.",
    )
