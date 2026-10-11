"""Propagation Engine: cycle-safe multi-path DFS, edge confidence weighting,
Personalized PageRank ranking, node centrality, path synthesis,
and yfinance event-study market validation.
"""
import json
import math
import os
from collections import defaultdict
from typing import Any, Dict, List, Optional, Set, Tuple

import networkx as nx

KIND_WEIGHTS = {
    "observed": 1.0,
    "knowledge": 0.9,
    "inferred": 0.7,
}


def get_kind_weight(kind: str) -> float:
    return KIND_WEIGHTS.get(kind, 0.8)


class PropagationEngine:
    def __init__(self, kb):
        self.kb = kb

    def _build_nx_graph(self, min_conf: float = 0.05) -> Tuple[nx.DiGraph, Dict[str, dict], Dict[str, List[dict]]]:
        """Build directed networkx graph from KB active nodes and edges."""
        graph_data = self.kb.graph(min_conf=min_conf)
        nodes_meta = {n["id"]: n for n in graph_data.get("nodes", [])}
        adj = defaultdict(list)

        G = nx.DiGraph()
        for n in graph_data.get("nodes", []):
            G.add_node(n["id"], **n)

        for e in graph_data.get("edges", []):
            u, v = e["from"], e["to"]
            adj[u].append(e)
            # Edge weight for PageRank: strength * confidence
            w = float(e.get("strength", 0.5)) * float(e.get("confidence", 0.5))
            G.add_edge(u, v, weight=max(0.01, w), **e)

        return G, nodes_meta, adj

    def trace_paths(
        self,
        trigger_node: str,
        trigger_sign: int = 1,
        min_conf: float = 0.05,
        max_depth: int = 4,
        as_of_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Trace paths from trigger node up to max_depth.
        Returns:
          - all_paths: list of all valid paths
          - best_paths_by_target: dict target -> primary path
          - alternative_paths_by_target: dict target -> list of alternate paths
          - affected_assets: ranked asset list
          - pagerank: Personalized PageRank dictionary
          - centrality: node degree centrality
        """
        G, nodes_meta, adj = self._build_nx_graph(min_conf=0.01)

        if trigger_node not in nodes_meta and trigger_node not in G:
            # If trigger node not present in graph, fallback to alias resolution
            for nid, meta in nodes_meta.items():
                aliases = meta.get("aliases") or []
                if trigger_node.lower() in [a.lower() for a in aliases]:
                    trigger_node = nid
                    break

        all_paths = []

        def dfs(curr_node: str, visited: Set[str], current_steps: List[dict], current_conf: float, current_sign: int):
            if len(current_steps) >= max_depth:
                return

            for edge in adj.get(curr_node, []):
                target = edge["to"]
                if target in visited:
                    continue  # Cycle prevention

                # Calculate decayed edge confidence
                decayed_conf = self.kb.calculate_decay(edge, as_of_date=as_of_date)
                kind = edge.get("kind", "knowledge")
                kind_wt = get_kind_weight(kind)
                step_conf = float(edge.get("strength", 0.5)) * kind_wt * (decayed_conf / max(0.01, float(edge.get("confidence") or 0.5)))
                path_conf = current_conf * step_conf

                if path_conf < min_conf:
                    continue

                edge_sign = int(edge.get("sign", 1))
                path_sign = current_sign * edge_sign

                art_ids = json.loads(edge.get("article_ids_json") or "[]")
                if edge.get("article_id") and edge["article_id"] not in art_ids:
                    art_ids.append(edge["article_id"])

                prior_score = 0.9 if kind == "knowledge" else 0.5
                llm_score = float(edge.get("confidence", 0.5)) if kind == "inferred" else 0.8
                step_obj = {
                    "from": curr_node,
                    "to": target,
                    "sign": edge_sign,
                    "confidence": round(step_conf, 3),
                    "conf": round(step_conf, 3),
                    "strength": edge.get("strength", 0.5),
                    "kind": edge.get("display_kind", kind),
                    "evidence_type": edge.get("display_kind", kind),
                    "reason": edge.get("reason", "Economic relationship"),
                    "evidence_text": edge.get("evidence_text", ""),
                    "source_article_ids": art_ids,
                    "score_parts": {
                        "prior": round(prior_score, 2),
                        "llm_conf": round(llm_score, 2),
                        "stat": 0.5,
                    },
                }

                new_steps = current_steps + [step_obj]
                has_inferred = any(s["kind"] == "inferred" for s in new_steps)
                path_kind = "inferred" if has_inferred else ("observed" if all(s["kind"] == "observed" for s in new_steps) else "knowledge")

                # Synthesize explanation
                expl = " -> ".join([s["from"] for s in new_steps] + [target]) + f": {new_steps[-1]['reason']}"

                path_record = {
                    "target": target,
                    "type": nodes_meta.get(target, {}).get("type", "Unknown"),
                    "confidence": round(path_conf, 3),
                    "conf": round(path_conf, 3),
                    "impact": path_sign,
                    "depth": len(new_steps),
                    "path_kind": path_kind,
                    "steps": new_steps,
                    "explanation": expl,
                }
                all_paths.append(path_record)

                dfs(target, visited | {target}, new_steps, path_conf, path_sign)

        if trigger_node in G:
            dfs(trigger_node, {trigger_node}, [], 1.0, trigger_sign)

        # Sort paths by confidence descending
        all_paths.sort(key=lambda p: p["confidence"], reverse=True)

        # Group paths by target asset
        paths_by_target = defaultdict(list)
        for p in all_paths:
            paths_by_target[p["target"]].append(p)

        best_paths = {}
        alt_paths = {}
        for target, paths in paths_by_target.items():
            best_paths[target] = paths[0]
            alt_paths[target] = paths[1:4]  # Top alternative paths

        # Personalized PageRank starting from trigger node
        pagerank = {}
        if trigger_node in G and len(G) > 0:
            try:
                personalization = {n: (1.0 if n == trigger_node else 0.0) for n in G.nodes}
                pagerank = nx.pagerank(G, alpha=0.85, personalization=personalization, weight="weight")
            except Exception:
                pagerank = {n: 1.0 / len(G) for n in G.nodes}

        # Centrality
        centrality = {}
        if len(G) > 0:
            try:
                centrality = nx.degree_centrality(G)
            except Exception:
                centrality = {n: 0.1 for n in G.nodes}

        # Build affected assets list
        ASSET_TYPES = {"Company", "Index", "Currency", "Commodity", "Sector"}
        affected_assets = []
        for target, best_p in best_paths.items():
            node_type = nodes_meta.get(target, {}).get("type", "Unknown")
            pr_val = pagerank.get(target, 0.0)
            affected_assets.append({
                "name": target,
                "type": node_type,
                "impact": best_p["impact"],
                "confidence": best_p["confidence"],
                "score": round(best_p["impact"] * best_p["confidence"], 3),
                "pagerank": round(pr_val, 4),
                "centrality": round(centrality.get(target, 0.0), 3),
                "path": best_p,
                "alt_paths": alt_paths.get(target, []),
            })

        # Rank affected assets: prioritize high confidence & PageRank
        affected_assets.sort(key=lambda a: (a["confidence"] * 0.6 + a["pagerank"] * 10 * 0.4), reverse=True)

        # Chains for UI display
        top_chains = list(best_paths.values())
        top_chains.sort(key=lambda p: p["confidence"], reverse=True)

        return {
            "trigger_node": trigger_node,
            "trigger_sign": trigger_sign,
            "all_paths": all_paths,
            "top_paths": top_chains[:12],
            "best_paths": best_paths,
            "affected_assets": affected_assets,
            "pagerank": pagerank,
            "centrality": centrality,
            "nodes_meta": nodes_meta,
        }


_VAL_CACHE: Dict[Tuple[str, str, int, int], Dict[str, Any]] = {}


def validate_asset_event_study(ticker: str, event_date: str, expected_sign: int = 1,
                               window: int = 3) -> Dict[str, Any]:
    """Perform event-study abnormal return validation using yfinance.
    Returns:
      status: 'confirmed' | 'contradicted' | 'inconclusive' | 'no_ticker' | 'unavailable'
      car_pct: Cumulative Abnormal Return in %
      z: z-score
    """
    if not ticker:
        return {"status": "no_ticker", "car_pct": None, "z": None, "ticker": None}

    cache_key = (ticker, event_date[:10], expected_sign, window)
    if cache_key in _VAL_CACHE:
        return dict(_VAL_CACHE[cache_key])

    import concurrent.futures

    def _fetch():
        import yfinance as yf
        from datetime import datetime, timedelta
        import numpy as np

        ev_dt = datetime.strptime(event_date[:10], "%Y-%m-%d")
        start_dt = ev_dt - timedelta(days=window * 4 + 10)
        end_dt = ev_dt + timedelta(days=window * 4 + 10)

        # Download asset price history
        ticker_data = yf.download(
            ticker,
            start=start_dt.strftime("%Y-%m-%d"),
            end=end_dt.strftime("%Y-%m-%d"),
            progress=False,
            auto_adjust=True,
            timeout=3.5,
        )
        return ticker_data

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            fut = ex.submit(_fetch)
            ticker_data = fut.result(timeout=4.0)
    except Exception as e:
        res = {"status": "unavailable", "car_pct": None, "z": None, "ticker": ticker, "error": str(e)}
        _VAL_CACHE[cache_key] = res
        return res

    try:
        import numpy as np


        if ticker_data is None or len(ticker_data) < 5:
            return {"status": "unavailable", "car_pct": None, "z": None, "ticker": ticker}

        # Calculate daily returns
        closes = ticker_data["Close"].dropna()
        if len(closes) < 5:
            return {"status": "unavailable", "car_pct": None, "z": None, "ticker": ticker}

        returns = closes.pct_change().dropna()
        # Find index closest to event date
        idx_dates = [d.strftime("%Y-%m-%d") for d in returns.index]
        match_idx = None
        for i, d in enumerate(idx_dates):
            if d >= event_date[:10]:
                match_idx = i
                break

        if match_idx is None:
            match_idx = len(returns) - 1

        # Event window returns [-1 to +window]
        w_start = max(0, match_idx - 1)
        w_end = min(len(returns), match_idx + window + 1)
        window_returns = returns.iloc[w_start:w_end]

        car = float(np.sum(np.asarray(window_returns)))
        car_pct = round(car * 100, 2)
        std = float(np.std(np.asarray(returns))) if len(returns) > 1 else 0.02
        z = round(car / (std * math.sqrt(len(window_returns)) + 1e-6), 2)

        if abs(z) < 1.0:
            status = "inconclusive"
        elif (car > 0 and expected_sign > 0) or (car < 0 and expected_sign < 0):
            status = "confirmed"
        else:
            status = "contradicted"

        res = {
            "status": status,
            "car_pct": car_pct,
            "z": z,
            "ticker": ticker,
        }
        _VAL_CACHE[cache_key] = res
        return res
    except Exception as e:
        res = {
            "status": "unavailable",
            "car_pct": None,
            "z": None,
            "ticker": ticker,
            "error": str(e),
        }
        _VAL_CACHE[cache_key] = res
        return res
