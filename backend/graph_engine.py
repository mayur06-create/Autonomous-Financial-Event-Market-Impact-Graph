import json, pathlib
import networkx as nx
from . import llm, market_data

KB = json.loads((pathlib.Path(__file__).parent / "knowledge_base.json").read_text())
NODE_META = {n["id"]: n for n in KB["nodes"]}
ALIAS = {}
for n in KB["nodes"]:
    ALIAS[n["id"].lower()] = n["id"]
    for a in n.get("aliases", []): ALIAS[a.lower()] = n["id"]

# Confidence weights per evidence type
BASE_WEIGHT = {"observed": 0.95, "knowledge": 1.0, "inferred": 0.5}
MAX_DEPTH, MIN_PATH_CONF, TOP_K = 4, 0.12, 6

G = nx.DiGraph()          # persistent, dynamic graph (merges across events)
EVENTS = []

def _norm(name):
    return ALIAS.get((name or "").lower().strip(), name)

def _add_node(name, typ=None):
    if name not in G:
        meta = NODE_META.get(name, {})
        G.add_node(name, type=meta.get("type", typ or "Unknown"), ticker=meta.get("ticker"))

def _add_edge(s, t, sign, conf, etype, reason="", evidence_text=""):
    _add_node(s); _add_node(t)
    if G.has_edge(s, t) and G[s][t]["confidence"] >= conf:
        return  # keep the stronger evidence on merge
    G.add_edge(s, t, sign=sign, confidence=round(conf, 3), evidence_type=etype,
               reason=reason, evidence_text=evidence_text, correlation=None, counter_evidence=False)

def load_knowledge():
    for n in KB["nodes"]: _add_node(n["id"])
    for e in KB["edges"]:
        _add_edge(e["source"], e["target"], e["sign"],
                  e["strength"] * BASE_WEIGHT["knowledge"], "knowledge", e["reason"])
load_knowledge()

def _validate_with_timeseries():
    for s, t, d in G.edges(data=True):
        if d["correlation"] is not None: continue
        c = market_data.correlation(G.nodes[s].get("ticker"), G.nodes[t].get("ticker"))
        if c is None: continue
        d["correlation"] = c
        agrees = (c > 0) == (d["sign"] > 0)
        if agrees: d["confidence"] = round(min(1.0, d["confidence"] + 0.1 * abs(c)), 3)
        elif abs(c) > 0.15:
            d["confidence"] = round(d["confidence"] * (1 - 0.3 * abs(c)), 3); d["counter_evidence"] = True

def _paths(start, start_sign):
    out = []
    def dfs(node, visited, steps, conf, sign):
        if len(steps) >= MAX_DEPTH: return
        for nxt in G.successors(node):
            if nxt in visited: continue
            d = G[node][nxt]
            c = conf * d["confidence"]
            if c < MIN_PATH_CONF: continue
            s = sign * d["sign"]
            step = {"from": node, "to": nxt, "sign": d["sign"], "confidence": d["confidence"],
                    "evidence_type": d["evidence_type"], "reason": d["reason"],
                    "evidence_text": d["evidence_text"], "correlation": d["correlation"],
                    "counter_evidence": d["counter_evidence"]}
            ns = steps + [step]
            out.append({"target": nxt, "steps": ns, "confidence": round(c, 3),
                        "impact": s, "depth": len(ns)})
            dfs(nxt, visited | {nxt}, ns, c, s)
    dfs(start, {start}, [], 1.0, start_sign)
    return out

def analyze(news: str):
    ex = llm.extract(news, ALIAS)
    ev = ex["event"]
    start = _norm(ev.get("primary_entity"))
    if not start:
        return {"error": "Could not identify a primary entity in the news."}
    _add_node(start)
    for e in ex.get("entities", []): _add_node(_norm(e["name"]), e.get("type"))
    for r in ex.get("observed_relations", []):
        _add_edge(_norm(r["source"]), _norm(r["target"]), int(r.get("sign", 1)),
                  0.9 * BASE_WEIGHT["observed"], "observed", "Stated in news", r.get("evidence_text", ""))
    for r in llm.infer(ev, list(G.nodes)):
        s, t = _norm(r["source"]), _norm(r["target"])
        if s in G and t in G and not G.has_edge(s, t):
            _add_edge(s, t, int(r.get("sign", 1)), float(r.get("confidence", 0.5)) * BASE_WEIGHT["inferred"],
                      "inferred", r.get("reason", ""))
    _validate_with_timeseries()

    start_sign = -1 if ev.get("direction") == "down" else 1
    all_paths = sorted(_paths(start, start_sign), key=lambda p: -p["confidence"])

    best = {}   # best (highest-confidence) path per target
    for p in all_paths:
        best.setdefault(p["target"], p)
    asset_types = {"Company", "Index", "Currency", "Commodity"}
    chains = [p for p in best.values() if G.nodes[p["target"]]["type"] in asset_types and p["depth"] >= 2]
    top = chains[:TOP_K] or list(best.values())[:TOP_K]   # show full chains down to tradable assets
    for p, text in zip(top, llm.explain(top)): p["explanation"] = text

    assets = [{"name": n, "type": G.nodes[n]["type"], "impact": p["impact"],
               "score": round(p["impact"] * p["confidence"], 3), "confidence": p["confidence"]}
              for n, p in best.items()]
    assets.sort(key=lambda a: -abs(a["score"]))

    EVENTS.append({"headline": ev.get("headline"), "start": start})
    reach = {start} | {s["to"] for p in top for s in p["steps"]} | {s["from"] for p in top for s in p["steps"]}
    sub = G.subgraph(reach)
    return {
        "event": ev, "start_node": start, "start_sign": start_sign,
        "nodes": [{"id": n, **d} for n, d in sub.nodes(data=True)],
        "edges": [{"source": s, "target": t, **d} for s, t, d in sub.edges(data=True)],
        "top_paths": top, "affected_assets": assets,
        "disclaimer": "Plausible impact chains, not predictions. Correlation is not causation.",
        "graph_size": {"nodes": G.number_of_nodes(), "edges": G.number_of_edges(), "events": len(EVENTS)},
    }
