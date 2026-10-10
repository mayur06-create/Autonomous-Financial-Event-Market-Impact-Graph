"""LLM layer: event + entity + relation extraction, and explanations.
Uses Claude if ANTHROPIC_API_KEY is set, else a keyword fallback so the demo never breaks."""
import json, os, re
from dotenv import load_dotenv
load_dotenv()

MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")
EVENT_TYPES = ["commodity_shock","interest_rate_decision","geopolitical_event",
               "regulatory_change","earnings_surprise","currency_move"]

def _client():
    if not os.getenv("ANTHROPIC_API_KEY"):
        return None
    import anthropic
    return anthropic.Anthropic()

def _json(text):
    text = re.sub(r"```json|```", "", text).strip()
    return json.loads(text[text.find("{"): text.rfind("}") + 1])

EXTRACT_PROMPT = """You are a financial event extraction engine.
Read the news text and return ONLY JSON (no prose, no markdown):
{{
 "event": {{"type": one of {types}, "headline": str, "direction": "up"|"down"|"neutral",
           "magnitude": str|null, "primary_entity": str}},
 "entities": [{{"name": str, "type": "Company|Commodity|Sector|Indicator|Index|Currency"}}],
 "observed_relations": [{{"source": str, "target": str, "sign": 1|-1, "evidence_text": "exact quote from the text"}}]
}}
Rules: "direction" describes the value of primary_entity. For rupee weakness use primary_entity "USD/INR" with direction "up". observed_relations ONLY if the text explicitly states the link. Never invent.
NEWS:
{news}"""

INFER_PROMPT = """Given these known graph node names: {nodes}
and this event: {event}
Propose up to 4 additional plausible causal links BETWEEN THESE NODES ONLY that are not obvious.
Return ONLY JSON: {{"inferred":[{{"source":str,"target":str,"sign":1|-1,"confidence":0-1,"reason":str}}]}}"""

EXPLAIN_PROMPT = """Explain each impact path to a non-expert in 2 short sentences.
Use ONLY the edges, evidence types and numbers given. Do not add new claims.
Say 'plausible', never 'will'. Mention if an edge is inferred (weaker) or has counter-evidence.
Return ONLY JSON: {{"explanations": [str, ...]}} in the same order as the paths.
PATHS: {paths}"""

def extract(news: str, alias_map: dict):
    c = _client()
    if c:
        try:
            r = c.messages.create(model=MODEL, max_tokens=1200, messages=[
                {"role":"user","content":EXTRACT_PROMPT.format(types=EVENT_TYPES, news=news)}])
            return _json(r.content[0].text)
        except Exception as e:
            print("LLM extract failed, using fallback:", e)
    return _fallback_extract(news, alias_map)

def _fallback_extract(news, alias_map):
    low = news.lower()
    hits = {}
    for alias in alias_map:
        m = re.search(r"\b" + re.escape(alias) + r"\b", low)
        if m and (alias_map[alias] not in hits or m.start() < hits[alias_map[alias]]):
            hits[alias_map[alias]] = m.start()
    found = sorted(hits, key=hits.get)          # order of first appearance in the text
    up = len(re.findall(r"\b(rise|rises|rose|surge|surges|jump|jumps|hike|hikes|hiked|spike|up)\b", low))
    down = len(re.findall(r"\b(fall|falls|fell|drop|drops|plunge|cut|cuts|slump|down|weakens|depreciates)\b", low))
    direction = "down" if down > up else "up"
    primary = found[0] if found else None
    if primary == "USD/INR" and re.search(r"\brupee\b", low):
        direction = "up" if direction == "down" else "down"   # rupee weak == USD/INR up
    mag = re.search(r"(\d+(?:\.\d+)?\s?(?:%|bps|basis points))", low)
    return {
        "event": {"type": "commodity_shock", "headline": news[:120], "direction": direction,
                  "magnitude": mag.group(1) if mag else None, "primary_entity": primary},
        "entities": [{"name": n, "type": "Unknown"} for n in found],
        "observed_relations": [],
    }

def infer(event, node_names):
    c = _client()
    if not c: return []
    try:
        r = c.messages.create(model=MODEL, max_tokens=600, messages=[
            {"role":"user","content":INFER_PROMPT.format(nodes=node_names, event=json.dumps(event))}])
        return _json(r.content[0].text).get("inferred", [])
    except Exception as e:
        print("LLM infer failed:", e); return []

def explain(paths):
    c = _client()
    if c:
        try:
            r = c.messages.create(model=MODEL, max_tokens=1500, messages=[
                {"role":"user","content":EXPLAIN_PROMPT.format(paths=json.dumps(paths))}])
            return _json(r.content[0].text)["explanations"]
        except Exception as e:
            print("LLM explain failed, using template:", e)
    return [_template(p) for p in paths]

def _template(p):
    steps = " → ".join(f'{s["to"]} ({"↑" if s["sign"]>0 else "↓"}, {s["evidence_type"]}, {s["confidence"]:.2f})' for s in p["steps"])
    return f'{p["steps"][0]["from"]} → {steps}. Plausible net effect on {p["target"]}: {"positive" if p["impact"]>0 else "negative"} (path confidence {p["confidence"]:.2f}).'
