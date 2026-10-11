"""NewsGraph API + static dashboard server.

Endpoints:
  GET  /api/status
  GET  /api/graph[?article=]
  GET  /api/kg[?types=&kinds=&min_conf=]
  GET  /api/kg/stats
  GET  /api/kg/node/<id>
  GET  /api/sectors
  GET  /api/timeseries[?sector=]
  GET  /api/articles
  GET  /api/article/<id>
  GET  /api/revisions
  GET  /api/news/live?search=&countries=&industries=&symbols=&limit=&pages=
  GET  /api/news/inbox[?status=]
  GET  /api/sector-analysis?article=<id>
  POST /api/analyze          {text?, article_id?, event_date?}
  POST /api/news/analyze     {uuids:[]}
  POST /api/ingest           {mode, force, search, ...}
  POST /api/validate         {assets:[], event_date, window}
  POST /api/reset
  GET  /api/jobs/<id>        job status and progress
"""
import concurrent.futures
from datetime import datetime, timezone
import hashlib
import json
import mimetypes
import threading
import time
import urllib.parse
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional

from . import compare, config, features, llm, market, news, nlp, pipeline
from .kb import KnowledgeBase
from .propagate import PropagationEngine, validate_asset_event_study
from .sector_analysis import analyze_sectors

STATIC = config.BASE_DIR / "static"
_ingest_lock = threading.Lock()

# Async job queue for background analysis
_JOBS: Dict[str, dict] = {}
_JOBS_LOCK = threading.Lock()
_JOB_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=3)


def _get_job(job_id: str) -> Optional[dict]:
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        return dict(job) if job else None


def _create_job(total: int) -> str:
    jid = f"job-{uuid.uuid4().hex[:10]}"
    with _JOBS_LOCK:
        _JOBS[jid] = {
            "job_id": jid,
            "status": "pending",
            "progress": {"completed": 0, "total": total},
            "results": [],
            "error": None,
            "created_at": time.time(),
        }
    return jid


def _update_job_progress(jid: str, completed: int, result: dict = None, error: str = None):
    with _JOBS_LOCK:
        if jid in _JOBS:
            _JOBS[jid]["status"] = "running"
            _JOBS[jid]["progress"]["completed"] = completed
            if result:
                _JOBS[jid]["results"].append(result)
            if error:
                _JOBS[jid]["results"].append({"error": error})


def _finish_job(jid: str, error: str = None):
    with _JOBS_LOCK:
        if jid in _JOBS:
            if error:
                _JOBS[jid]["status"] = "failed"
                _JOBS[jid]["error"] = error
            else:
                _JOBS[jid]["status"] = "completed"
            _JOBS[jid]["finished_at"] = time.time()

# Presets for live-news fetch
SEARCH_PRESETS = {
    "india-markets":  {"search": "India markets stock NSE BSE Sensex Nifty",
                       "countries": "in", "language": "en"},
    "crude-energy":   {"search": "crude oil brent OPEC energy prices",
                       "countries": "in,us", "language": "en"},
    "rbi-rates":      {"search": "RBI repo rate inflation India monetary policy",
                       "countries": "in", "language": "en"},
    "banking":        {"search": "India banking HDFC ICICI SBI NPA credit",
                       "countries": "in", "language": "en"},
    "tech":           {"search": "India IT Infosys TCS Wipro tech earnings",
                       "countries": "in,us", "language": "en"},
}


def _near_dup_title(t1: str, t2: str) -> bool:
    """Rough near-duplicate check via character-level Jaccard on words."""
    s1 = set(t1.lower().split())
    s2 = set(t2.lower().split())
    if not s1 or not s2:
        return False
    j = len(s1 & s2) / len(s1 | s2)
    return j > 0.75


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, body: bytes, ctype="application/json", code=200):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(json.dumps(obj).encode("utf-8"), code=code)

    def do_OPTIONS(self):
        self._send(b"", code=204)

    # ---------------------------------------------------------------- GET
    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        kb: KnowledgeBase = self.server.kb
        p = u.path
        try:
            # ---- /api/status ----
            if p == "/api/status":
                engines = nlp.get_nlp_engines()
                gemini_st = llm.get_gemini_status()
                m_st = news.get_marketaux_status()
                return self._json({
                    "marketaux": m_st["state"] == "ready",
                    "marketaux_status": m_st,
                    "gemini": gemini_st,
                    "stats": kb.stats(),
                    "engines": engines,
                    "presets": list(SEARCH_PRESETS.keys()),
                })

            # ---- /api/jobs/<id> ----
            if p.startswith("/api/jobs/"):
                job_id = p.rsplit("/", 1)[1]
                job = _get_job(job_id)
                if not job:
                    return self._json({"error": "job not found"}, 404)
                return self._json(job)

            # ---- /api/graph ----
            if p == "/api/graph":
                return self._json(kb.graph((q.get("article") or [None])[0]))

            # ---- /api/kg ----
            if p == "/api/kg":
                arts_raw = q.get("articles") or q.get("article")
                article_ids = [a.strip() for a in arts_raw[0].split(",") if a.strip()] if arts_raw else None
                secs_raw = q.get("sectors") or q.get("sector")
                sectors = [s.strip() for s in secs_raw[0].split(",") if s.strip()] if secs_raw else None
                depth = int((q.get("depth") or [2])[0])
                types = q.get("types")[0].split(",") if q.get("types") else None
                kinds = q.get("kinds")[0].split(",") if q.get("kinds") else None
                sign_raw = (q.get("sign") or [None])[0]
                sign = int(sign_raw) if sign_raw is not None and sign_raw != "" else None
                min_conf = float((q.get("min_conf") or [0.0])[0])
                from_date = (q.get("from") or [None])[0]
                to_date = (q.get("to") or [None])[0]
                inc_ev = (q.get("include_events") or ["1"])[0] not in ("0", "false", "False")

                return self._json(kb.graph(
                    article_ids=article_ids,
                    sectors=sectors,
                    depth=depth,
                    kinds=kinds,
                    types=types,
                    sign=sign,
                    min_conf=min_conf,
                    from_date=from_date,
                    to_date=to_date,
                    include_events=inc_ev,
                ))

            # ---- /api/kg/stats ----
            if p == "/api/kg/stats":
                return self._json(kb.stats())

            # ---- /api/kg/node/<id> ----
            if p.startswith("/api/kg/node/"):
                node_id = urllib.parse.unquote(p[len("/api/kg/node/"):])
                details = kb.get_node_details(node_id)
                if not details:
                    return self._json({"error": "node not found"}, 404)
                return self._json(details)

            # ---- /api/kg/edge/<id> ----
            if p.startswith("/api/kg/edge/"):
                edge_id = urllib.parse.unquote(p[len("/api/kg/edge/"):])
                details = kb.get_edge_details(edge_id)
                if not details:
                    return self._json({"error": "edge not found"}, 404)
                return self._json(details)

            # ---- /api/sectors ----
            if p == "/api/sectors":
                return self._json(kb.sectors())

            # ---- /api/timeseries ----
            if p == "/api/timeseries":
                return self._json(kb.timeseries((q.get("sector") or [None])[0]))

            # ---- /api/articles ----
            if p == "/api/articles":
                return self._json(kb.articles())

            # ---- /api/revisions ----
            if p == "/api/revisions":
                return self._json(kb.revisions())

            # ---- /api/article/<id> ----
            if p.startswith("/api/article/"):
                a = kb.article(urllib.parse.unquote(p.rsplit("/", 1)[1]))
                return self._json(a, 200) if a else self._json({"error": "not found"}, 404)

            # ---- /api/news/inbox ----
            if p == "/api/news/inbox":
                status = (q.get("status") or [None])[0]
                limit = int((q.get("limit") or [200])[0])
                arts = kb.inbox_list(status=status, limit=limit)
                all_inbox = kb.inbox_list(limit=500)
                pending_count = len([a for a in all_inbox if a.get("status") in ("new", "pending")])
                return self._json({"total": len(arts), "pending": pending_count, "articles": arts})

            # ---- /api/news/live ----
            if p == "/api/news/live":
                search      = (q.get("search") or [""])[0].strip()
                countries   = (q.get("countries") or ["in"])[0]
                industries  = (q.get("industries") or [None])[0]
                symbols     = (q.get("symbols") or [None])[0]
                limit       = int((q.get("limit") or [10])[0])
                pages       = int((q.get("pages") or [1])[0])
                language    = (q.get("language") or ["en"])[0]
                preset      = (q.get("preset") or [None])[0]
                sample_mode = (q.get("sample") or ["0"])[0] == "1"

                # Apply preset overrides
                if preset and preset in SEARCH_PRESETS:
                    p_cfg = SEARCH_PRESETS[preset]
                    search     = search or p_cfg.get("search", search)
                    countries  = p_cfg.get("countries", countries)
                    language   = p_cfg.get("language", language)

                if sample_mode or not config.marketaux_key():
                    arts = news.load_sample()
                    items = [_article_to_inbox_item(a, "SAMPLE") for a in arts]
                    kb.inbox_upsert(items)
                    return self._json({
                        "source": "sample",
                        "warning": "No MARKETAUX_API_KEY — showing sample data (clearly labelled SAMPLE).",
                        "articles": kb.inbox_list(limit=100),
                    })

                try:
                    arts = news.fetch_news(
                        search=search or None,
                        symbols=symbols,
                        industries=industries,
                        countries=countries,
                        language=language,
                        limit=limit,
                        pages=pages,
                    )
                    items = [_article_to_inbox_item(a, search or "live") for a in arts]
                    # Near-dup dedup before insert
                    existing_titles = [r["title"] for r in kb.inbox_list(limit=500)]
                    items = [
                        it for it in items
                        if not any(_near_dup_title(it["title"], et) for et in existing_titles)
                    ]
                    new_count = kb.inbox_upsert(items)
                    return self._json({
                        "source": "live",
                        "fetched": len(arts),
                        "new": new_count,
                        "articles": kb.inbox_list(limit=200),
                    })
                except news.MarketauxError as e:
                    cached = kb.inbox_list(limit=200)
                    return self._json({
                        "source": "cached",
                        "error": e.message,
                        "code": e.code,
                        "marketaux_status": news.get_marketaux_status(),
                        "articles": cached,
                    }, 200)
                except Exception as e:
                    err = str(e)
                    # Quota / auth errors — serve cached inbox
                    cached = kb.inbox_list(limit=200)
                    return self._json({
                        "source": "cached",
                        "error": err,
                        "marketaux_status": news.get_marketaux_status(),
                        "articles": cached,
                    }, 200)

            # ---- /api/sector-analysis ----
            if p == "/api/sector-analysis":
                article_id = (q.get("article") or [None])[0]
                scope = (q.get("scope") or ["article"])[0]

                if scope == "all" or not article_id:
                    # Aggregate across all sector_impacts
                    sectors_data = kb.sectors()
                    ts_data = kb.timeseries()
                    return self._json({"scope": "all", "sectors": sectors_data, "timeseries": ts_data})

                # Per-article sector analysis requires the article in KB
                art = kb.article(article_id) if article_id else None
                if not art:
                    # Try inbox
                    inbox_item = kb.inbox_get(article_id)
                    if inbox_item:
                        return self._json({"error": "Article not yet analyzed. POST /api/news/analyze first."}, 400)
                    return self._json({"error": "article not found"}, 404)

                # Get sector_impacts from DB for this article
                llm_impacts = kb._all(
                    "SELECT * FROM sector_impacts WHERE article_id=? ORDER BY ABS(score) DESC",
                    (article_id,)
                )

                # Run propagation for this article's trigger
                feats_json = art.get("features_json", "{}")
                try:
                    feats = json.loads(feats_json or "{}")
                except Exception:
                    feats = {}

                primary_ev = feats.get("primary_event_meta")
                trig_node = (primary_ev or {}).get("trigger_node")
                if not trig_node:
                    for e in feats.get("entities", []):
                        if e.get("node_type") in ("Commodity", "Indicator", "Currency", "Sector"):
                            trig_node = e.get("linked_node_id")
                            break
                if not trig_node:
                    trig_node = "Inflation"

                trig_sign = (primary_ev or {}).get("sign", 1)
                prop = PropagationEngine(kb)
                prop_res = prop.trace_paths(trig_node, trig_sign, min_conf=0.05, as_of_date=art.get("published_at"))
                sector_results = analyze_sectors(prop_res, llm_sector_impacts=llm_impacts, article_id=article_id)
                ts_data = kb.timeseries()

                return self._json({
                    "article_id": article_id,
                    "article_title": art.get("title", ""),
                    "trigger": {"node": trig_node, "sign": trig_sign},
                    "sectors": sector_results,
                    "timeseries": ts_data,
                    "disclaimer": "Plausible impact estimates from the knowledge graph, not predictions.",
                })

            # ---- /api/market/reaction ----
            if p == "/api/market/reaction":
                article_id = (q.get("article") or [None])[0]
                if not article_id:
                    return self._json({"error": "article parameter is required"}, 400)
                assets_raw = (q.get("assets") or [None])[0]
                assets = [a.strip() for a in assets_raw.split(",") if a.strip()] if assets_raw else None
                pre = int((q.get("pre") or [30])[0])
                post = int((q.get("post") or [10])[0])
                try:
                    res = market.run_article_reaction_study(kb, article_id=article_id, asset_names=assets, pre_window=pre, post_window=post)
                    return self._json(res)
                except ValueError as ve:
                    return self._json({"error": str(ve)}, 400)
                except Exception as ex:
                    return self._json({"error": f"{type(ex).__name__}: {ex}"}, 500)

            # ---- /api/market/sector-reaction ----
            if p == "/api/market/sector-reaction":
                article_id = (q.get("article") or [None])[0]
                if not article_id:
                    return self._json({"error": "article parameter is required"}, 400)
                try:
                    secs = kb._all("SELECT sector, score FROM sector_impacts WHERE article_id=? ORDER BY ABS(score) DESC LIMIT 4", (article_id,))
                    sec_names = [s["sector"] for s in secs]
                    if not sec_names:
                        sec_names = ["Banking & Finance", "Aviation", "Energy"]
                    res = market.run_article_reaction_study(kb, article_id=article_id, asset_names=sec_names)
                    return self._json(res)
                except ValueError as ve:
                    return self._json({"error": str(ve)}, 400)
                except Exception as ex:
                    return self._json({"error": f"{type(ex).__name__}: {ex}"}, 500)

            # ---- /api/market/scorecard ----
            if p == "/api/market/scorecard":
                try:
                    res = market.compute_aggregate_scorecard(kb)
                    return self._json(res)
                except Exception as ex:
                    return self._json({"error": f"{type(ex).__name__}: {ex}"}, 500)

            # ---- static files ----
            if p == "/" or p == "":
                p = "/index.html"
            f = (STATIC / p.lstrip("/")).resolve()
            if STATIC.resolve() in f.parents and f.is_file():
                return self._send(f.read_bytes(), mimetypes.guess_type(f.name)[0] or "application/octet-stream")

            self._json({"error": "not found"}, 404)
        except Exception as e:  # noqa: BLE001
            self._json({"error": f"{type(e).__name__}: {e}"}, 500)

    # ---------------------------------------------------------------- POST
    def do_POST(self):
        kb: KnowledgeBase = self.server.kb
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
        except Exception:
            return self._json({"error": "invalid JSON"}, 400)

        p = self.path

        if p == "/api/reset":
            kb.reset()
            return self._json({"ok": True})

        if p in ("/api/validate", "/validate"):
            assets = body.get("assets", [])
            event_date = body.get("event_date", "2022-02-24")
            window = int(body.get("window", 3))

            def _val_item(item):
                name = item.get("name", "")
                ticker = item.get("ticker")
                sign = int(item.get("expected_sign", 1))
                val_res = validate_asset_event_study(ticker, event_date, expected_sign=sign, window=window)
                val_res["name"] = name
                return val_res

            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
                results = list(ex.map(_val_item, assets))
            return self._json({"results": results, "event_date": event_date})

        # ---- /api/news/analyze: analyze inbox articles ----
        if p == "/api/news/analyze":
            uuids = body.get("uuids", [])
            if not uuids:
                return self._json({"error": "uuids list is required"}, 400)

            # Check if synchronous execution was requested
            u_parsed = urllib.parse.urlparse(self.path)
            u_query = urllib.parse.parse_qs(u_parsed.query)
            is_sync = u_query.get("sync", ["0"])[0] == "1" or body.get("sync") is True

            jid = _create_job(len(uuids))

            def _worker():
                for idx, uid in enumerate(uuids):
                    try:
                        res = _analyze_inbox_article(kb, uid)
                        _update_job_progress(jid, idx + 1, result=res)
                    except Exception as ex:
                        _update_job_progress(jid, idx + 1, error=f"{type(ex).__name__}: {ex}")
                _finish_job(jid)

            if is_sync:
                _worker()
                return self._json(_get_job(jid))
            else:
                _JOB_EXECUTOR.submit(_worker)
                return self._json({
                    "job_id": jid,
                    "status": "pending",
                    "total": len(uuids),
                    "message": f"Queued {len(uuids)} article(s) for asynchronous analysis.",
                })

        # ---- /api/analyze: analyze pasted headline or article_id ----
        if p in ("/api/analyze", "/analyze"):
            text = (body.get("text") or "").strip()
            article_id = body.get("article_id")
            event_date = body.get("event_date")

            if not text and not article_id:
                return self._json({"error": "text or article_id is required"}, 400)

            try:
                result = _run_analysis(kb, text=text, article_id=article_id, event_date=event_date,
                                       min_conf=float(body.get("min_conf", 0.05)))
                return self._json(result)
            except Exception as e:
                return self._json({"error": f"{type(e).__name__}: {e}"}, 500)

        # ---- /api/ingest ----
        if p == "/api/ingest":
            if not _ingest_lock.acquire(blocking=False):
                return self._json({"error": "an ingest is already running"}, 409)
            try:
                mode = body.get("mode", "sample")
                out = pipeline.run_ingest(
                    kb,
                    mode=mode,
                    force=bool(body.get("force")),
                    search=body.get("search"),
                    symbols=body.get("symbols"),
                    industries=body.get("industries"),
                    limit=body.get("limit"),
                    pages=body.get("pages"),
                )
                return self._json(out)
            except RuntimeError as e:
                return self._json({"error": str(e)}, 400)
            except Exception as e:  # noqa: BLE001
                return self._json({"error": f"{type(e).__name__}: {e}"}, 500)
            finally:
                _ingest_lock.release()

        self._json({"error": "not found"}, 404)


# ---------------------------------------------------------------- helpers

def _article_to_inbox_item(art, search_query: str) -> dict:
    """Convert a news.Article to a news_inbox row dict."""
    ents = [
        {k: e.get(k) for k in ("name", "symbol", "industry", "type", "country", "sentiment_score")}
        for e in (art.entities or [])
    ]
    scores = [e["sentiment_score"] for e in ents if e.get("sentiment_score") is not None]
    return {
        "uuid": art.uuid,
        "title": art.title,
        "description": art.description,
        "url": art.url,
        "source": art.source,
        "published_at": art.published_at,
        "image_url": None,
        "entities": ents,
        "sentiment_marketaux": (sum(scores) / len(scores)) if scores else None,
        "search_query": search_query,
    }


def _run_analysis(kb, text: str = "", article_id: str = None,
                  event_date: str = None, min_conf: float = 0.05) -> dict:
    """Core analysis pipeline shared by /api/analyze and /api/news/analyze."""
    if article_id and kb.has_article(article_id):
        saved_art = kb.article(article_id)
        text = text or saved_art.get("title", "")
        pub_date = event_date or saved_art.get("published_at") or "2024-01-01"
        uid = article_id
        try:
            feats = json.loads(saved_art.get("features_json") or "{}")
        except Exception:
            feats = {}
        analysis = {
            "summary": saved_art.get("summary", ""),
            "engine": saved_art.get("engine", "cached"),
            "sector_impacts": saved_art.get("sector_impacts", []),
        }
    else:
        if article_id and not text:
            saved_art = kb.article(article_id)
            if not saved_art:
                raise ValueError(f"article {article_id} not found in KB")
            text = saved_art["title"]
            event_date = saved_art["published_at"]

        h = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
        uid = article_id or f"art-{h}"
        pub_date = event_date or "2024-01-01"
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if pub_date and str(pub_date)[:10] > today_str:
            pub_date = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        art = news.Article(
            uuid=uid,
            title=text,
            description=text,
            snippet="",
            url="",
            source="headline",
            published_at=pub_date,
            sentiment_score=None,
            entities=[],
        )

        feats = features.extract_features(art)
        emb = nlp.embed_article(art.title, art.text)
        related = kb.find_related(emb, art.published_at, exclude_id=art.uuid)
        analysis = llm.analyze(art, feats, related)

        if not kb.has_article(art.uuid):
            kb.save_analysis(art, feats, analysis, embedding=emb)
            compare.build_revisions(kb, art, analysis, related)

    primary_ev = feats.get("primary_event_meta")
    trig_node = (primary_ev or {}).get("trigger_node")
    if not trig_node:
        for e in feats.get("entities", []):
            if e["node_type"] in ("Commodity", "Indicator", "Currency", "Sector"):
                trig_node = e["linked_node_id"]
                break
    if not trig_node:
        trig_node = "Crude Oil" if "oil" in text.lower() or "brent" in text.lower() else "Inflation"

    sent_obj = feats.get("sentiment")
    sent_score = sent_obj.get("score", 0.0) if isinstance(sent_obj, dict) else float(sent_obj or 0.0)
    trig_sign = (primary_ev or {}).get("sign", 1) if primary_ev else (
        1 if sent_score >= 0 else -1
    )

    prop = PropagationEngine(kb)
    prop_res = prop.trace_paths(trig_node, trig_sign, min_conf=min_conf, as_of_date=pub_date)

    # Sector analysis
    sector_results = analyze_sectors(
        prop_res,
        llm_sector_impacts=analysis.get("sector_impacts", []),
        article_id=uid,
    )

    art_graph = kb.graph(article_id=uid)
    all_graph = kb.graph()
    chain_nodes = (
        {s["from"] for path in prop_res["top_paths"] for s in path["steps"]} |
        {s["to"] for path in prop_res["top_paths"] for s in path["steps"]} |
        {trig_node}
    )
    merged_nodes = {
        n["id"]: n for n in all_graph["nodes"]
        if n["id"] in chain_nodes or n["id"] in {x["id"] for x in art_graph["nodes"]}
    }
    merged_edges = [
        e for e in all_graph["edges"]
        if e["from"] in merged_nodes and e["to"] in merged_nodes
    ]

    kpis = {
        "positive": len([a for a in prop_res["affected_assets"] if a["impact"] > 0]),
        "negative": len([a for a in prop_res["affected_assets"] if a["impact"] < 0]),
        "avg_confidence": round(
            sum(path["confidence"] for path in prop_res["top_paths"]) /
            max(1, len(prop_res["top_paths"])), 3
        ) if prop_res["top_paths"] else 0.0,
        "chains_traced": len(prop_res["all_paths"]),
        "sectors_affected": len(sector_results),
    }

    mag = (feats.get("numbers") or [None])[0]
    return {
        "article_id": uid,
        "article_title": text,
        "start_node": trig_node,
        "start_sign": trig_sign,
        "event": {
            "primary_entity": trig_node,
            "direction": "up" if trig_sign > 0 else "down",
            "magnitude": mag,
            "event_type": (primary_ev or {}).get("event_type", "macro"),
        },
        "nodes": list(merged_nodes.values()),
        "edges": merged_edges,
        "top_paths": prop_res["top_paths"],
        "affected_assets": prop_res["affected_assets"],
        "sector_analysis": sector_results,
        "kpis": kpis,
        "graph_size": {"nodes": len(merged_nodes), "edges": len(merged_edges)},
        "engines": {
            **feats.get("models", {}),
            "llm": analysis.get("engine", "heuristic-fallback"),
        },
        "mode": "llm" if "gemini" in analysis.get("engine", "") else "fallback",
        "disclaimer": (
            "Plausible impact chains based on curated economic rules and the knowledge graph. "
            "Not investment advice or predictions."
        ),
    }


def _analyze_inbox_article(kb, uuid: str) -> dict:
    """Look up inbox item, run full pipeline, mark as analyzed."""
    inbox_item = kb.inbox_get(uuid)
    if not inbox_item:
        raise ValueError(f"Inbox item '{uuid}' not found. Fetch live news first.")

    entities = inbox_item.get("entities", [])
    art = news.Article(
        uuid=uuid,
        title=inbox_item["title"],
        description=inbox_item.get("description", ""),
        snippet="",
        url=inbox_item.get("url", ""),
        source=inbox_item.get("source", ""),
        published_at=inbox_item.get("published_at", ""),
        sentiment_score=inbox_item.get("sentiment_marketaux"),
        entities=entities,
    )

    result = _run_analysis(kb, text=art.text, article_id=uuid, event_date=art.published_at)
    kb.inbox_mark_analyzed(uuid)
    return {**result, "uuid": uuid, "status": "analyzed"}


def make_server(host, port, kb):
    srv = ThreadingHTTPServer((host, port), Handler)
    srv.kb = kb
    return srv


def _warmup_models():
    """Pre-warm NLP models and validate Gemini in background so requests are immediate."""
    try:
        llm.get_gemini_status()
        nlp.get_nlp_engines()
        nlp.extract_entities("Warmup")
        nlp.analyze_sentiment("Markets traded positive today.")
        nlp.classify_events("RBI policy repo rate hike")
        nlp.get_embedder()
    except Exception as e:
        pass


def serve(host="127.0.0.1", port=8000, kb=None):
    kb = kb or KnowledgeBase()
    # Kick off background pre-warming of Gemini and NLP pipelines
    import threading as _t
    _t.Thread(target=_warmup_models, daemon=True).start()
    srv = make_server(host, port, kb)
    print(
        f"NewsGraph dashboard: http://{host}:{srv.server_address[1]}  "
        f"(Marketaux: {'yes' if config.marketaux_key() else 'no'}, "
        f"Gemini key: {'yes' if config.gemini_key() else 'no'})"
    )
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
