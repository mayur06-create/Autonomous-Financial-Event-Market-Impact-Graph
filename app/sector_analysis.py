"""Sector impact analysis: multi-path aggregation, noisy-OR confidence,
KG/LLM blending, horizon scoring, and top-company extraction.
"""
import math
from typing import Any, Dict, List, Optional


# Config weights — can be overridden per call
_W_KG = 0.6
_W_LLM = 0.4


CANONICAL_SECTORS = {
    "banking": "Banking & Finance",
    "banking & finance": "Banking & Finance",
    "banks": "Banking & Finance",
    "auto": "Automobile",
    "automobile": "Automobile",
    "autos": "Automobile",
    "real estate": "Real Estate",
    "realty": "Real Estate",
    "energy": "Energy",
    "oil marketing cos": "Energy",
    "upstream oil & gas": "Energy",
    "it services": "IT Services",
    "it": "IT Services",
    "aviation": "Aviation",
    "pharma": "Pharma & Healthcare",
    "pharma & healthcare": "Pharma & Healthcare",
    "fmcg": "FMCG",
    "paints & chemicals": "Paints & Chemicals",
    "metals & mining": "Metals & Mining",
    "telecom": "Telecom",
}


def canonical_sector(name: str) -> str:
    s = (name or "").replace("sector:", "").strip()
    if not s:
        return ""
    return CANONICAL_SECTORS.get(s.lower(), s.title())


def _noisy_or(confidences: List[float], cap: float = 0.95) -> float:
    """1 - prod(1 - ci), capped at cap."""
    p = 1.0
    for c in confidences:
        p *= max(0.0, 1.0 - c)
    return min(cap, 1.0 - p)


def _net_score(signed_confs: List[float]) -> float:
    """tanh(sum(sign_i * conf_i))"""
    return round(math.tanh(sum(signed_confs)), 3)


def analyze_sectors(
    prop_result: Dict[str, Any],
    llm_sector_impacts: Optional[List[dict]] = None,
    article_id: Optional[str] = None,
    w_kg: float = _W_KG,
    w_llm: float = _W_LLM,
) -> List[Dict[str, Any]]:
    """
    Compute per-sector impact from propagation paths + LLM sector impacts.

    Args:
        prop_result:        Output from PropagationEngine.trace_paths()
        llm_sector_impacts: list of {sector, score, horizon, confidence, explanation}
        article_id:         Optionally tag the results.
        w_kg / w_llm:       Blend weights.

    Returns:
        list of {sector, direction, net_score, confidence, horizon, score_parts,
                 top_paths, top_companies, mechanism, evidence_sentences,
                 validation_status}
    """
    all_paths = prop_result.get("all_paths", [])

    # ---- 1. Group paths ending at each sector node ----
    sector_paths: Dict[str, List[dict]] = {}
    for path in all_paths:
        steps = path.get("steps", [])
        if not steps:
            continue
        terminal = steps[-1].get("to", "")
        # Check node type from steps
        for s in steps:
            if s.get("to") == terminal:
                pass
        # Also collect partial path contributions for every intermediate sector node
        for i, step in enumerate(steps):
            to_node = step.get("to", "")
            to_type = step.get("to_type", "").lower()
            if "sector" in to_type or to_node.startswith("sector:") or canonical_sector(to_node) in CANONICAL_SECTORS.values():
                sec_raw = canonical_sector(to_node)
                if not sec_raw:
                    continue
                sector_paths.setdefault(sec_raw, [])
                sub_steps = steps[:i+1]
                sub_conf = path.get("confidence", 0.5) * (0.9 ** (len(steps) - i - 1))
                sector_paths[sec_raw].append({
                    "steps": sub_steps,
                    "confidence": sub_conf,
                    "impact": step.get("sign", 1) * sub_conf,
                    "sign": step.get("sign", 1),
                    "path_str": " → ".join(
                        ([steps[0].get("from", "")] if steps else []) +
                        [s.get("to", "") for s in sub_steps]
                    ),
                })

    # Also use affected_assets to find sector-level entries
    for asset in prop_result.get("affected_assets", []):
        atype = asset.get("type", "").lower()
        aname = asset.get("id", "")
        if "sector" in atype or aname.startswith("sector:"):
            sec_raw = canonical_sector(aname)
            if sec_raw and sec_raw not in sector_paths:
                sector_paths[sec_raw] = []

    # ---- 2. LLM impacts map ----
    llm_map: Dict[str, dict] = {}
    for imp in (llm_sector_impacts or []):
        s = canonical_sector(imp.get("sector", ""))
        if s:
            llm_map[s] = imp

    # ---- 3. Merge all known sectors (strictly non-empty) ----
    all_sectors = {s for s in (set(sector_paths.keys()) | set(llm_map.keys())) if s and s.strip()}

    results = []
    for sector in sorted(all_sectors):
        paths = sector_paths.get(sector, [])
        llm = llm_map.get(sector, {})

        # KG-derived score
        if paths:
            signed_confs = [p["impact"] for p in paths]
            confidences  = [abs(p["confidence"]) for p in paths]
            kg_score = _net_score(signed_confs)
            kg_conf  = _noisy_or(confidences)
        else:
            kg_score = 0.0
            kg_conf  = 0.0

        # LLM-derived score
        llm_score = float(llm.get("score", 0.0))
        llm_conf  = float(llm.get("confidence", 0.0))

        # Blended
        if kg_conf > 0 and llm_conf > 0:
            final_score = w_kg * kg_score + w_llm * llm_score
            final_conf  = _noisy_or([kg_conf * w_kg, llm_conf * w_llm])
        elif kg_conf > 0:
            final_score = kg_score
            final_conf  = kg_conf
        else:
            final_score = llm_score
            final_conf  = llm_conf

        # Direction
        direction = "positive" if final_score > 0.05 else "negative" if final_score < -0.05 else "neutral"

        # Horizon: prefer LLM horizon, else estimate from path depth
        horizon = llm.get("horizon", "short")
        if paths:
            avg_depth = sum(len(p["steps"]) for p in paths) / max(1, len(paths))
            if avg_depth >= 3 and horizon == "short":
                horizon = "medium"

        # Top 3 contributing paths (by |impact|)
        top_paths = sorted(paths, key=lambda p: abs(p.get("impact", 0)), reverse=True)[:3]
        path_share_total = sum(abs(p.get("impact", 0)) for p in top_paths) or 1.0
        top_paths_out = [
            {
                "path": p.get("path_str", ""),
                "impact": round(p.get("impact", 0), 3),
                "confidence": round(p.get("confidence", 0), 3),
                "share_pct": round(100 * abs(p.get("impact", 0)) / path_share_total, 1),
                "reason": (p.get("steps") or [{}])[-1].get("reason", ""),
            }
            for p in top_paths
        ]

        # Evidence sentences from step reasons
        evidence = []
        for p in top_paths:
            for step in p.get("steps", []):
                r = step.get("reason", "")
                if r and r not in evidence:
                    evidence.append(r)
        evidence = evidence[:3]

        # Top companies in this sector from affected_assets
        top_companies = []
        for asset in prop_result.get("affected_assets", []):
            asset_sector = asset.get("sector", "") or ""
            if sector.lower() in asset_sector.lower() or asset_sector.lower() in sector.lower():
                top_companies.append({
                    "id": asset.get("id"),
                    "label": asset.get("label", asset.get("id", "")),
                    "ticker": asset.get("ticker"),
                    "impact": asset.get("impact", 0),
                    "sign": asset.get("sign", 0),
                })
        top_companies = sorted(top_companies, key=lambda x: abs(x.get("impact", 0)), reverse=True)[:5]

        # Mechanism text
        mechanism = llm.get("explanation", "")
        if not mechanism and paths:
            mechanism = "; ".join(
                f"{p['path_str']} (impact {p['impact']:+.2f})" for p in top_paths[:2]
            )

        results.append({
            "sector": sector,
            "direction": direction,
            "net_score": round(final_score, 3),
            "confidence": round(final_conf, 3),
            "horizon": horizon,
            "score_parts": {
                "kg": round(kg_score, 3),
                "llm": round(llm_score, 3),
                "kg_conf": round(kg_conf, 3),
                "llm_conf": round(llm_conf, 3),
                "blended": round(final_score, 3),
            },
            "top_paths": top_paths_out,
            "top_companies": top_companies,
            "mechanism": mechanism,
            "evidence_sentences": evidence,
            "validation_status": None,  # filled later by event-study if tickers available
            "article_id": article_id,
        })

    # Sort by |net_score| descending
    results.sort(key=lambda x: abs(x["net_score"]), reverse=True)
    return results
