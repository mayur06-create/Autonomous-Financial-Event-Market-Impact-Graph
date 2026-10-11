"""Zero-shot event classification with directional sign.
Default model: MoritzLaurer/deberta-v3-base-zeroshot-v2.0 (override via NEWSGRAPH_ZEROSHOT_MODEL).
"""
import os
import re
from typing import Any, Dict, List, Optional

from .base import cached_result, get_device, get_mock

DEFAULT_ZEROSHOT_MODEL = "MoritzLaurer/deberta-v3-base-zeroshot-v2.0"
HYPOTHESIS_TEMPLATE = "This financial news indicates {}."

# Mapping table label -> {event_type, family, trigger_node, sign}
LABEL_EVENT_MAP: Dict[str, Dict[str, Any]] = {
    "commodity price rise": {
        "event_type": "oil_surge",
        "family": "crude_oil",
        "trigger_node": "Crude Oil",
        "sign": 1,
    },
    "commodity price fall": {
        "event_type": "oil_drop",
        "family": "crude_oil",
        "trigger_node": "Crude Oil",
        "sign": -1,
    },
    "interest rate hike": {
        "event_type": "rate_hike",
        "family": "monetary_policy",
        "trigger_node": "Repo Rate",
        "sign": 1,
    },
    "interest rate cut": {
        "event_type": "rate_cut",
        "family": "monetary_policy",
        "trigger_node": "Repo Rate",
        "sign": -1,
    },
    "rate hold / pause": {
        "event_type": "rate_hold",
        "family": "monetary_policy",
        "trigger_node": "Repo Rate",
        "sign": 1,
    },
    "banking liquidity tightening / reserve requirement": {
        "event_type": "liquidity_tightening",
        "family": "monetary_policy",
        "trigger_node": "CRR",
        "sign": 1,
    },
    "monetary easing / liquidity infusion": {
        "event_type": "liquidity_infusion",
        "family": "monetary_policy",
        "trigger_node": "CRR",
        "sign": -1,
    },
    "inflation rises": {
        "event_type": "inflation_up",
        "family": "inflation",
        "trigger_node": "Inflation",
        "sign": 1,
    },
    "inflation falls": {
        "event_type": "inflation_down",
        "family": "inflation",
        "trigger_node": "Inflation",
        "sign": -1,
    },
    "currency depreciation": {
        "event_type": "currency_depreciation",
        "family": "currency",
        "trigger_node": "USD/INR",
        "sign": 1,
    },
    "currency appreciation": {
        "event_type": "currency_appreciation",
        "family": "currency",
        "trigger_node": "USD/INR",
        "sign": -1,
    },
    "regulatory change": {
        "event_type": "regulation",
        "family": "regulation",
        "trigger_node": "SEBI",
        "sign": -1,
    },
    "geopolitical supply disruption": {
        "event_type": "supply_disruption",
        "family": "supply",
        "trigger_node": "Crude Oil",
        "sign": 1,
    },
    "earnings beat": {
        "event_type": "earnings_beat",
        "family": "earnings",
        "trigger_node": None,
        "sign": 1,
    },
    "earnings miss": {
        "event_type": "earnings_miss",
        "family": "earnings",
        "trigger_node": None,
        "sign": -1,
    },
    "foreign fund outflow/inflow": {
        "event_type": "fii_flows",
        "family": "fii_flows",
        "trigger_node": "FII Flows",
        "sign": 1,
    },
    "M&A": {
        "event_type": "merger",
        "family": "merger",
        "trigger_node": None,
        "sign": 1,
    },
}

_ZEROSHOT_PIPELINE = None


def get_zeroshot_model_name() -> str:
    return os.getenv("NEWSGRAPH_ZEROSHOT_MODEL", DEFAULT_ZEROSHOT_MODEL).strip()


def get_zeroshot_pipeline():
    global _ZEROSHOT_PIPELINE
    mock = get_mock("zeroshot")
    if mock is not None:
        return mock

    if _ZEROSHOT_PIPELINE is not None:
        return _ZEROSHOT_PIPELINE

    model_name = get_zeroshot_model_name()
    try:
        from transformers import AutoModelForSequenceClassification, AutoTokenizer, pipeline
        device = 0 if get_device() == "cuda" else -1
        tokenizer = AutoTokenizer.from_pretrained(model_name)
        model = AutoModelForSequenceClassification.from_pretrained(model_name)
        _ZEROSHOT_PIPELINE = pipeline(
            "zero-shot-classification",
            model=model,
            tokenizer=tokenizer,
            device=device,
        )
        return _ZEROSHOT_PIPELINE
    except ImportError:
        raise RuntimeError("transformers and torch are required for zero-shot classification.")
    except Exception as e:
        raise RuntimeError(f"Failed to load zero-shot model '{model_name}': {e}")


def _select_plausible_labels(text: str, all_labels: List[str]) -> List[str]:
    low = text.lower()
    selected = set()
    if any(w in low for w in ("oil", "crude", "brent", "opec", "energy", "fuel")):
        selected.update(["commodity price rise", "commodity price fall", "geopolitical supply disruption"])
    if any(w in low for w in ("rate", "rates", "repo", "rbi", "crr", "liquidity", "monetary", "central bank", "bps", "cash reserve")):
        selected.update([
            "interest rate hike", "interest rate cut", "rate hold / pause",
            "banking liquidity tightening / reserve requirement",
            "monetary easing / liquidity infusion"
        ])
    if any(w in low for w in ("inflation", "cpi", "wpi", "price rise", "costs")):
        selected.update(["inflation rises", "inflation falls"])
    if any(w in low for w in ("rupee", "dollar", "usd", "inr", "currency", "forex")):
        selected.update(["currency depreciation", "currency appreciation"])
    if any(w in low for w in ("profit", "loss", "earnings", "revenue", "quarter", "results")):
        selected.update(["earnings beat", "earnings miss"])
    if any(w in low for w in ("sebi", "regulat", "probe", "ban", "rule", "rules")):
        selected.update(["regulatory change", "banking liquidity tightening / reserve requirement"])
    if any(w in low for w in ("merger", "acqui", "takeover", "buyout")):
        selected.update(["M&A"])

    filtered = [l for l in all_labels if l in selected]
    return filtered if len(filtered) >= 2 else all_labels


def classify_events(text: str, candidate_labels: Optional[List[str]] = None,
                    threshold: float = 0.35) -> Dict[str, Any]:
    """Multi-label zero-shot classification mapping directly to typed directional events."""
    mock = get_mock("event_classifier")
    if mock is not None:
        return mock(text)

    def _compute():
        all_avail_labels = list(LABEL_EVENT_MAP.keys())
        labels = candidate_labels or _select_plausible_labels(text, all_avail_labels)
        model_name = get_zeroshot_model_name()
        if os.getenv("NEWSGRAPH_OFFLINE") == "1":
            return _keyword_event_fallback(text, labels, "NEWSGRAPH_OFFLINE=1")
        try:
            pipe = get_zeroshot_pipeline()
            res = pipe(
                text,
                candidate_labels=labels,
                hypothesis_template=HYPOTHESIS_TEMPLATE,
                multi_label=True,
            )
            raw_labels = res.get("labels", [])
            raw_scores = res.get("scores", [])
            engine = f"zeroshot:{model_name}"
        except Exception as e:
            # Fallback keyword-informed classifier when zero-shot weights not loaded
            return _keyword_event_fallback(text, labels, str(e))

        detected_events = []
        for lab, score in zip(raw_labels, raw_scores):
            if score >= threshold and lab in LABEL_EVENT_MAP:
                meta = LABEL_EVENT_MAP[lab]
                detected_events.append({
                    "label": lab,
                    "score": round(float(score), 3),
                    "event_type": meta["event_type"],
                    "type": meta["event_type"],
                    "family": meta["family"],
                    "trigger_node": meta["trigger_node"],
                    "sign": meta["sign"],
                })

        # Sort by confidence score descending
        detected_events.sort(key=lambda x: x["score"], reverse=True)

        return {
            "events": detected_events,
            "primary_event": detected_events[0] if detected_events else None,
            "engine": engine,
        }

    return cached_result("zeroshot_events", text, _compute)


def _keyword_event_fallback(text: str, labels: List[str], reason: str) -> Dict[str, Any]:
    """Robust fallback mapping for offline execution or tests."""
    low = text.lower()
    scores = {}

    # Signal detectors for labels with proximity to subject
    if re.search(r"\b(crude|oil|brent)\b[^.]{0,40}\b(surg\w*|jump\w*|spike\w*|ris\w*|rose|gain\w*|rally\w*|higher)\b|\b(surg\w*|jump\w*|spike\w*)\b[^.]{0,40}\b(crude|oil|brent)\b", low):
        scores["commodity price rise"] = 0.94
    if re.search(r"\b(crude|oil|brent)\b[^.]{0,40}\b(falls?|fell|drops?|dropping|slumps?|plung\w*|slides?|slid|declines?|declining|lower|eases?|easing|eased)\b|\b(falls?|fell|drops?|slumps?|plung\w*|slides?|slid)\b[^.]{0,40}\b(crude|oil|brent)\b", low):
        scores["commodity price fall"] = 0.95
        scores.pop("commodity price rise", None)
    if re.search(r"\b(supply[- ](chain )?(disruption|shortage)|shortage|outage|shutdown|middle east disruption)\b", low):
        scores["geopolitical supply disruption"] = 0.90
    if re.search(r"\b(rate|rates|repo)\b", low) and re.search(r"\b(hike\w*|rais\w*|lift\w*|increas\w*)\b", low):
        scores["interest rate hike"] = 0.95
    if re.search(r"\b(rate|rates|repo)\b", low) and re.search(r"\b(cut\w*|lower\w*|slash\w*|reduc\w*)\b", low):
        scores["interest rate cut"] = 0.95
    if re.search(r"\b(rate|rates|repo)\b", low) and re.search(r"\b(hold\w*|pause\w*|unchanged|steady)\b", low):
        scores["rate hold / pause"] = 0.96
        # A pause after earlier hike is a pause, not a hike
        scores.pop("interest rate hike", None)
    if re.search(r"\b(crr|cash reserve|reserve rules?|reserve ratio|liquidity)\b", low) and re.search(r"\b(tighten\w*|absorb\w*|drain\w*|elevat\w*|curb\w*)\b", low):
        scores["banking liquidity tightening / reserve requirement"] = 0.95
    if re.search(r"\b(crr|cash reserve|liquidity)\b", low) and re.search(r"\b(eas\w*|cut\w*|inject\w*|infus\w*|surplus)\b", low):
        scores["monetary easing / liquidity infusion"] = 0.95
    if re.search(r"\b(rbi|central bank)\b", low) and re.search(r"\b(tighten\w*|drain\w*|hawk\w*)\b", low) and not scores.get("banking liquidity tightening / reserve requirement") and not scores.get("rate hold / pause"):
        scores["interest rate hike"] = 0.91
    if re.search(r"\binflation\b", low) and re.search(r"\b(ris\w*|rose|high\w*|accelerat\w*|jump\w*|surg\w*|climb\w*)\b", low):
        scores["inflation rises"] = 0.93
    if re.search(r"\binflation\b", low) and re.search(r"\b(falls?|fell|cools?|cooling|drops?|slows?|eases?|easing|declines?)\b", low):
        scores["inflation falls"] = 0.93
    if re.search(r"\b(rupee|inr)\b", low) and re.search(r"\b(fall\w*|fell|depreciat\w*|weak\w*|slip\w*|plung\w*|slid\w*)\b", low):
        scores["currency depreciation"] = 0.92
    if re.search(r"\b(rupee|inr)\b", low) and re.search(r"\b(gain\w*|appreciat\w*|firm\w*|strong\w*|advanc\w*)\b", low):
        scores["currency appreciation"] = 0.92
    if re.search(r"\b(sebi|regulat\w*|probe|ban\w*|penalty)\b", low):
        scores["regulatory change"] = 0.88
    if re.search(r"\b(beat\w*|top\w*|surpass\w*)\b", low) and re.search(r"\b(estimate\w*|expectation\w*|profit|revenue)\b", low):
        scores["earnings beat"] = 0.89
    if re.search(r"\b(miss\w*|fall\w* short)\b", low) and re.search(r"\b(estimate\w*|expectation\w*|profit|revenue)\b", low):
        scores["earnings miss"] = 0.89
    if re.search(r"\b(merger\w*|acqui\w*|buyout)\b", low):
        scores["M&A"] = 0.87

    detected = []
    for lab, sc in scores.items():
        if lab in LABEL_EVENT_MAP:
            meta = LABEL_EVENT_MAP[lab]
            detected.append({
                "label": lab,
                "score": sc,
                "event_type": meta["event_type"],
                "type": meta["event_type"],
                "family": meta["family"],
                "trigger_node": meta["trigger_node"],
                "sign": meta["sign"],
            })
    detected.sort(key=lambda x: x["score"], reverse=True)

    return {
        "events": detected,
        "primary_event": detected[0] if detected else None,
        "engine": f"fallback_classifier ({reason})",
    }
