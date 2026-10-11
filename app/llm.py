"""Phase 3: relationship extraction with Gemini (REST, no SDK needed).

If GEMINI_API_KEY is missing, or a call fails, a rule-based fallback (rules.py) produces the same output
shape and the result is labelled with its engine, so nothing is silently faked.
"""
import json
import re
import threading
import time
import urllib.error
import urllib.request

from . import config, rules

ENTITY_TYPES = {"macro", "company", "commodity", "sector"}
EFFECTS = {"positive", "negative", "mixed", "neutral"}
_KNOWN_SECTORS = {s.lower(): s for s in rules.SECTORS}

# Cached Gemini model validation result
_GEMINI_STATUS: dict = {}   # {state, model, detail}
_GEMINI_LOCK = threading.Lock()

# Circuit breaker state
_CB_DISABLED_UNTIL: float = 0.0   # epoch seconds
_CB_FAILURE_COUNT: int = 0
_CB_DISABLE_SECS: int = 600        # 10 minutes
_CB_LOCK = threading.Lock()

# Hard errors that should immediately trip the circuit breaker
_CB_FATAL_CODES = {401, 403, 404}


def _cb_is_open() -> bool:
    """Return True if circuit breaker is tripped (Gemini should not be called)."""
    with _CB_LOCK:
        return _CB_DISABLED_UNTIL > time.time()


def _cb_record_failure(code: int, detail: str) -> None:
    global _CB_FAILURE_COUNT, _CB_DISABLED_UNTIL
    with _CB_LOCK:
        _CB_FAILURE_COUNT += 1
        if code in _CB_FATAL_CODES or _CB_FAILURE_COUNT >= 2:
            _CB_DISABLED_UNTIL = time.time() + _CB_DISABLE_SECS
            _CB_FAILURE_COUNT = 0


def _cb_record_success() -> None:
    global _CB_FAILURE_COUNT, _CB_DISABLED_UNTIL
    with _CB_LOCK:
        _CB_FAILURE_COUNT = 0
        _CB_DISABLED_UNTIL = 0.0


def cb_disable_reason() -> str | None:
    """Return the human-readable reason Gemini is disabled, or None if it's active."""
    if _cb_is_open():
        remaining = max(0, int(_CB_DISABLED_UNTIL - time.time()))
        return f"circuit-broken for {remaining}s after repeated API errors"
    return None


def _validate_gemini_model() -> dict:
    """Call ListModels and verify the configured model supports generateContent.
    Returns {state: ready|error, model, detail}.
    """
    key = config.gemini_key()
    if not key:
        return {"state": "error", "model": config.gemini_model(), "detail": "GEMINI_API_KEY not set in .env"}

    model_name = config.gemini_model()
    list_url = "https://generativelanguage.googleapis.com/v1beta/models"
    req = urllib.request.Request(
        list_url,
        headers={"x-goog-api-key": key, "User-Agent": "newsgraph/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:200]
        return {"state": "error", "model": model_name,
                "detail": f"ListModels HTTP {e.code}: {body}"}
    except Exception as e:
        return {"state": "error", "model": model_name, "detail": f"ListModels unreachable: {e}"}

    available = []
    for m in data.get("models", []):
        mn = m.get("name", "")
        short = mn.split("/")[-1]
        if "generateContent" in m.get("supportedGenerationMethods", []):
            available.append(short)

    if not available:
        return {"state": "error", "model": model_name,
                "detail": "No models with generateContent found on this key"}

    if model_name not in available:
        suggestions = available[:3]
        return {
            "state": "error",
            "model": model_name,
            "detail": (
                f"Model '{model_name}' not found or does not support generateContent. "
                f"Try one of: {', '.join(suggestions)}. "
                f"Set GEMINI_MODEL=<name> in .env"
            ),
        }
    return {"state": "ready", "model": model_name, "detail": ""}


def get_gemini_status(force_recheck: bool = False) -> dict:
    """Return cached Gemini status, checking at most once per process start."""
    global _GEMINI_STATUS
    with _GEMINI_LOCK:
        if not _GEMINI_STATUS or force_recheck:
            _GEMINI_STATUS = _validate_gemini_model()
    st = dict(_GEMINI_STATUS)
    reason = cb_disable_reason()
    if reason:
        st["state"] = "fallback"
        st["cb_detail"] = reason
    return st


def has_gemini() -> bool:
    return not _cb_is_open() and get_gemini_status().get("state") == "ready"


# ---------------------------------------------------------------- Gemini transport
def _parse_json(text: str) -> dict:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        return json.loads(text)
    except ValueError:
        a, b = text.find("{"), text.rfind("}")
        if a >= 0 and b > a:
            return json.loads(text[a:b + 1])
        raise


def _call_gemini(prompt: str, retries: int = 1) -> dict:
    """Call Gemini with 20s timeout, 1 retry, circuit breaker."""
    if _cb_is_open():
        raise RuntimeError(f"circuit breaker open: {cb_disable_reason()}")

    url = f"{config.GEMINI_BASE}/{config.gemini_model()}:generateContent"
    body = json.dumps({
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"},
    }).encode()
    last = "unknown error"
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=body, headers={
            "Content-Type": "application/json", "x-goog-api-key": config.gemini_key()})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                data = json.load(r)
            result = _parse_json(data["candidates"][0]["content"]["parts"][0]["text"])
            _cb_record_success()
            return result
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
            _cb_record_failure(e.code, last)
            # Fatal codes: don't retry
            if e.code in _CB_FATAL_CODES:
                break
            if e.code in (429, 500, 503) and attempt < retries:
                time.sleep(2 ** attempt)
                continue
            break
        except (KeyError, IndexError, ValueError) as e:
            last = f"{type(e).__name__}: {e}"
            if attempt < retries:
                time.sleep(1)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = f"{type(e).__name__}: {e}"
            _cb_record_failure(0, last)
            break
    raise RuntimeError(last)



# ---------------------------------------------------------------- prompts
ANALYSIS_PROMPT = """You are a financial news analyst building a knowledge graph of how news affects market sectors.
Use ONLY the article and the extracted features below. Do not invent facts. When the impact is uncertain, lower the
strength / confidence and say so in the reason.

ARTICLE
title: <<TITLE>>
published_at: <<DATE>>
text: <<TEXT>>

EXTRACTED FEATURES (output of the tokenization / NLP step)
<<FEATURES>>

PRIOR RELATED NEWS ALREADY IN THE KNOWLEDGE BASE (may be empty)
<<PRIOR>>

Return ONLY valid JSON with exactly this shape:
{
  "summary": "<= 2 sentences",
  "relations": [
    {"source": "name", "source_type": "macro|company|commodity|sector",
     "target": "name", "target_type": "macro|company|commodity|sector",
     "relation": "short verb phrase, e.g. raises costs of",
     "effect": "positive|negative|mixed|neutral",
     "strength": 0.0-1.0,
     "reason": "why this relationship exists, grounded in the article",
     "impact": "how this news affects the target: mechanism, short vs long term"}
  ],
  "sector_impacts": [
    {"sector": "one of: <<SECTORS>>", "score": -1.0..1.0, "horizon": "short|medium|long",
     "confidence": 0.0-1.0, "explanation": "why and how this news moves this sector"}
  ]
}
Rules: 3-8 relations, each with a reason. Sector score negative = bad for the sector, positive = good.
Use only the listed sector names. Use entity names exactly as they appear in the features when possible."""

COMPARE_PROMPT = """You compare a NEW financial news item with an EARLIER related one that is already in a knowledge base.
Explain what changed for each affected sector, using only the data below.

EARLIER NEWS (<<PDATE>>): <<PTITLE>>
earlier summary: <<PSUMMARY>>
NEW NEWS (<<NDATE>>): <<NTITLE>>
new summary: <<NSUMMARY>>

PER-SECTOR CHANGE (score -1..1, negative = bad for the sector)
<<DELTAS>>

Return ONLY valid JSON:
{"pros": ["one sentence per sector that benefits from the new news vs the earlier one"],
 "cons": ["one sentence per sector that is hurt or still under pressure"],
 "net_effect": "positive|negative|mixed|neutral",
 "explanation": "3-5 sentences: what changed versus the old news, why, and how each sector is impacted"}"""


def build_analysis_prompt(article, feats, related) -> str:
    compact = {
        "events": [e["label"] for e in feats["events"]],
        "entities": [{k: e[k] for k in ("name", "type", "sector") if e.get(k)} for e in feats["entities"]],
        "sector_candidates": feats["sectors"][:6],
        "keywords": [k["keyword"] for k in feats["keywords"]],
        "bigrams": feats["bigrams"][:6],
        "numbers": feats["numbers"],
        "sentiment": feats["sentiment"],
    }
    prior = [{"title": r["title"], "date": r["published_at"][:10], "summary": r.get("summary", ""),
              "sector_scores": r["scores"]} for r in related] or "none"
    return (ANALYSIS_PROMPT.replace("<<TITLE>>", article.title).replace("<<DATE>>", article.published_at)
            .replace("<<TEXT>>", article.text).replace("<<FEATURES>>", json.dumps(compact, indent=1))
            .replace("<<PRIOR>>", json.dumps(prior, indent=1) if prior != "none" else "none")
            .replace("<<SECTORS>>", ", ".join(rules.SECTORS)))


# ---------------------------------------------------------------- validation
def _clamp(v, lo, hi, default):
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return default


def _etype(v):
    v = str(v or "").strip().lower()
    return v if v in ENTITY_TYPES else "company"


def _canon(name, typ):
    name = str(name).strip()
    return _KNOWN_SECTORS.get(name.lower(), name) if typ == "sector" else name


def normalize_analysis(obj: dict, engine: str) -> dict:
    rels = []
    for r in obj.get("relations") or []:
        st, tt = _etype(r.get("source_type")), _etype(r.get("target_type"))
        src, tgt = _canon(r.get("source", ""), st), _canon(r.get("target", ""), tt)
        if not src or not tgt or src.lower() == tgt.lower():
            continue
        eff = str(r.get("effect", "")).lower()
        rels.append({"source": src, "source_type": st, "target": tgt, "target_type": tt,
                     "relation": str(r.get("relation") or "affects")[:80],
                     "effect": eff if eff in EFFECTS else "neutral",
                     "strength": _clamp(r.get("strength"), 0, 1, 0.5),
                     "reason": str(r.get("reason") or "")[:700], "impact": str(r.get("impact") or "")[:700]})
    imps = []
    for i in obj.get("sector_impacts") or []:
        sector = _KNOWN_SECTORS.get(str(i.get("sector", "")).strip().lower())
        if not sector:
            continue
        hz = str(i.get("horizon", "short")).lower()
        imps.append({"sector": sector, "score": round(_clamp(i.get("score"), -1, 1, 0.0), 3),
                     "horizon": hz if hz in ("short", "medium", "long") else "short",
                     "confidence": round(_clamp(i.get("confidence"), 0, 1, 0.5), 2),
                     "explanation": str(i.get("explanation") or "")[:900]})
    if not rels and not imps:
        raise ValueError("empty analysis")
    return {"summary": str(obj.get("summary") or "")[:500], "relations": rels[:12],
            "sector_impacts": imps, "engine": engine}


# ---------------------------------------------------------------- offline fallback engine
def _effect(score):
    return "positive" if score > 0.1 else "negative" if score < -0.1 else "neutral"


def heuristic_analysis(article, feats, note: str) -> dict:
    ents = feats["entities"]
    detected = [s["sector"] for s in feats["sectors"]]
    drivers = [e for e in ents if e["type"] in ("macro", "commodity")] or \
              [e for e in ents if e["type"] == "company"][:1]
    relations, impacts = [], {}
    for ev in feats["events"]:
        if drivers:
            # pick the driver that matches the event family when possible
            pref = {"monetary_policy": "RBI", "crude_oil": "Crude Oil"}.get(ev["family"])
            drv = next((d for d in drivers if d["name"] == pref), drivers[0])
            src, st = drv["name"], drv["type"]
        else:
            src, st = ev["label"], "macro"
        for sector, score, why in rules.effects_for(ev["type"], detected):
            relations.append({"source": src, "source_type": st, "target": sector, "target_type": "sector",
                              "relation": f"{ev['label'].lower()} impacts", "effect": _effect(score),
                              "strength": round(abs(score), 2),
                              "reason": f"Detected '{ev['label']}' in the article. {why}",
                              "impact": f"{rules.EVENT_HORIZON.get(ev['type'], 'short')}-term "
                                        f"{'tailwind' if score > 0 else 'headwind'} for {sector} "
                                        f"(rule score {score:+.2f})."})
            if sector not in impacts or abs(score) > abs(impacts[sector]["score"]):
                impacts[sector] = {"sector": sector, "score": score,
                                   "horizon": rules.EVENT_HORIZON.get(ev["type"], "short"),
                                   "confidence": 0.55,
                                   "explanation": f"{ev['label']}: {why}"}
    if not impacts:  # no recognised event: fall back to article sentiment x sector relevance
        s = feats["sentiment"]["score"]
        for sec in feats["sectors"][:2]:
            sc = round(s * sec["relevance"], 3)
            impacts[sec["sector"]] = {"sector": sec["sector"], "score": sc, "horizon": "short", "confidence": 0.3,
                                      "explanation": f"No known event pattern; score derived from article sentiment "
                                                     f"({s:+.2f}) x sector relevance ({sec['relevance']})."}
    for e in ents:  # company exposure edges from per-entity sentiment
        sc = e.get("sentiment")
        if e["type"] == "company" and e.get("sector") and sc is not None and abs(sc) >= 0.15:
            relations.append({"source": e["sector"], "source_type": "sector", "target": e["name"],
                              "target_type": "company", "relation": "sector exposure", "effect": _effect(sc),
                              "strength": round(min(1, abs(sc)), 2),
                              "reason": f"{e['name']} belongs to {e['sector']} and its sentiment in this news is {sc:+.2f}.",
                              "impact": "Stock-level reaction follows the sector-level pressure or relief."})
    summary = article.title + (" Detected: " + ", ".join(e["label"] for e in feats["events"]) + "."
                               if feats["events"] else "")
    return {"summary": summary[:500], "relations": relations[:12], "sector_impacts": list(impacts.values()),
            "engine": f"heuristic-rules ({note})"}


def analyze(article, feats, related) -> dict:
    if not config.gemini_key():
        return heuristic_analysis(article, feats, "no GEMINI_API_KEY set")
    try:
        obj = _call_gemini(build_analysis_prompt(article, feats, related))
        return normalize_analysis(obj, f"gemini:{config.gemini_model()}")
    except Exception as e:  # noqa: BLE001 - any failure falls back, and is recorded in the engine label
        return heuristic_analysis(article, feats, f"Gemini failed: {e}")


def enrich_comparison(new, prior, rows):
    """Ask Gemini to write pros/cons/explanation for a revision. Returns a dict or None."""
    if not has_gemini():
        return None
    deltas = [{"sector": r["sector"], "earlier": r["prior"], "new": r["new"], "reason_new": r["reason"]} for r in rows]
    prompt = (COMPARE_PROMPT.replace("<<PDATE>>", prior["published_at"][:10]).replace("<<PTITLE>>", prior["title"])
              .replace("<<PSUMMARY>>", prior.get("summary", "")).replace("<<NDATE>>", new["published_at"][:10])
              .replace("<<NTITLE>>", new["title"]).replace("<<NSUMMARY>>", new.get("summary", ""))
              .replace("<<DELTAS>>", json.dumps(deltas, indent=1)))
    try:
        obj = _call_gemini(prompt)
        ne = str(obj.get("net_effect", "")).lower()
        return {"pros": [str(x) for x in obj.get("pros", [])][:8], "cons": [str(x) for x in obj.get("cons", [])][:8],
                "net_effect": ne if ne in EFFECTS else None, "explanation": str(obj.get("explanation", ""))[:1500],
                "engine": f"gemini:{config.gemini_model()}"}
    except Exception:  # noqa: BLE001
        return None
