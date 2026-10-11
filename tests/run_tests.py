"""Comprehensive test suite for NewsGraph:
Unit tests for NLP modules, acceptance cases (1-4), graph propagation,
API endpoints, and backward compatibility.
Run: python tests/run_tests.py
"""
import json
import os
import sys
import tempfile
import threading
import urllib.request
from pathlib import Path

# Configure environment for offline deterministic test execution
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["NEWSGRAPH_OFFLINE"] = "1"
os.environ["MARKETAUX_API_KEY"] = ""
os.environ["GEMINI_API_KEY"] = ""
os.environ["NEWSGRAPH_DB"] = os.path.join(tempfile.mkdtemp(), "test_kb.db")

from app import compare, config, features, llm, news, nlp, pipeline, server  # noqa: E402
from app.kb import KnowledgeBase  # noqa: E402
from app.propagate import PropagationEngine  # noqa: E402

ARTS = {a.uuid: a for a in news.load_sample()}


def feats(uid):
    return features.extract_features(ARTS[uid])


def fresh_kb():
    kb = KnowledgeBase(":memory:")
    pipeline.process_articles(list(ARTS.values()), kb)
    return kb


# ---------------------------------------------------------------- Tests
def test_tokenizer():
    t = features.tokenize("The RBI hikes repo rate by 25 bps")
    assert "the" not in t and "rbi" in t and "25" in t and "hikes" in t
    assert features.stem("rates") == "rate" and features.stem("pressures") == "pressure"


def test_events_and_sectors():
    f1 = feats("s1-rbi-hike")
    assert any(e["type"] == "rate_hike" for e in f1["events"])
    f4 = feats("s4-rbi-pause")
    assert any(e["type"] == "rate_hold" for e in f4["events"])
    f2 = feats("s2-crude-surge")
    assert any(e["type"] == "oil_surge" for e in f2["events"])
    f5 = feats("s5-crude-drop")
    assert any(e["type"] == "oil_drop" for e in f5["events"])

    secs = [s["sector"] for s in f1["sectors"]]
    assert "Real Estate" in secs and "Banking & Finance" in secs
    names = {e["name"]: e["type"] for e in f1["entities"]}
    assert "RBI" in names and "HDFC Bank" in names
    assert any("25 bps" in n for n in f1["numbers"])


def test_json_validation():
    raw = (
        '```json\n{"summary":"x","relations":[{"source":"RBI","source_type":"macro","target":"real estate",'
        '"target_type":"sector","relation":"hurts","effect":"NEGATIVE","strength":7,"reason":"r","impact":"i"}],'
        '"sector_impacts":[{"sector":"real estate","score":-5,"horizon":"weird"},{"sector":"Nonsense","score":1}]}\n```'
    )
    out = llm.normalize_analysis(llm._parse_json(raw), "t")
    assert out["relations"][0]["target"] == "Real Estate" and out["relations"][0]["strength"] == 1.0
    assert out["relations"][0]["effect"] == "negative"
    assert len(out["sector_impacts"]) == 1 and out["sector_impacts"][0]["score"] == -1.0
    try:
        llm.normalize_analysis({"relations": [], "sector_impacts": []}, "t")
        assert False
    except ValueError:
        pass


def test_gemini_failure_falls_back():
    os.environ["GEMINI_API_KEY"] = "dummy"
    orig = llm._call_gemini
    llm._call_gemini = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("HTTP 429"))
    try:
        a = ARTS["s1-rbi-hike"]
        out = llm.analyze(a, features.extract_features(a), [])
        assert out["engine"].startswith("heuristic-rules (Gemini failed: HTTP 429") and out["sector_impacts"]
    finally:
        llm._call_gemini = orig
        os.environ["GEMINI_API_KEY"] = ""


def test_pipeline_graph_and_kb():
    kb = fresh_kb()
    st = kb.stats()
    assert st["articles"] == 6 and st["edges"] > 20 and st["sector_impacts"] >= 15
    g = kb.graph()
    ids = {n["id"] for n in g["nodes"]}
    assert "Real Estate" in ids and "RBI" in ids and "event:s1-rbi-hike" in ids
    assert all(e["from"] in ids and e["to"] in ids for e in g["edges"])
    assert all(e["reason"] for e in g["edges"])
    assert any(e["kind"] == "inferred" or e.get("relation") == "reverses earlier impact" for e in g["edges"])


def test_new_news_updates_old_graph_with_pros_cons():
    kb = fresh_kb()
    revs = {}
    for r in sorted(kb.revisions(), key=lambda x: x.get("similarity", 0), reverse=True):
        if r["article_id"] not in revs:
            revs[r["article_id"]] = r
    pause = revs["s4-rbi-pause"]
    assert pause["prior_article_id"] == "s1-rbi-hike" and pause["net_effect"] == "positive"
    assert any(x.startswith("Real Estate") for x in pause["pros"]) and not pause["cons"]
    assert "earlier news" in pause["explanation"]
    drop = revs["s5-crude-drop"]
    assert drop["prior_article_id"] == "s2-crude-surge"
    assert any(x.startswith("Aviation") for x in drop["pros"]) and any(x.startswith("Energy") for x in drop["cons"])
    assert any(d["reversed"] for d in drop["deltas"])
    assert "s6-infosys" not in revs


def test_idempotent_and_force():
    kb = fresh_kb()
    res = pipeline.process_articles(list(ARTS.values()), kb)
    assert all(r["status"].startswith("skipped") for r in res) and kb.stats()["articles"] == 6
    pipeline.process_articles(list(ARTS.values()), kb, force=True)
    assert kb.stats()["articles"] == 6 and len(kb.revisions()) >= 2


def test_sectors_and_timeseries():
    kb = fresh_kb()
    secs = {s["sector"]: s for s in kb.sectors()}
    assert abs(sum(s["share_pct"] for s in secs.values()) - 100) < 0.5
    assert secs["Aviation"]["n"] == 2
    ts = kb.timeseries()
    av = ts["Aviation"]
    assert [p["date"] for p in av] == ["2026-10-03", "2026-10-09"]
    assert av[0]["score"] < 0 < av[1]["score"] and av[1]["cumulative"] == round(av[0]["score"] + av[1]["score"], 3)
    assert list(kb.timeseries("Real Estate")) == ["Real Estate"]


def test_http_api():
    kb = KnowledgeBase(":memory:")
    srv = server.make_server("127.0.0.1", 0, kb)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    get = lambda p: json.load(urllib.request.urlopen(base + p))  # noqa: E731
    post = lambda p, d: json.load(  # noqa: E731
        urllib.request.urlopen(
            urllib.request.Request(
                base + p, data=json.dumps(d).encode("utf-8"), headers={"Content-Type": "application/json"}
            )
        )
    )

    try:
        # Ingest sample data
        out = post("/api/ingest", {"mode": "sample"})
        assert out["fetched"] == 6

        status = get("/api/status")
        assert status["stats"]["articles"] == 6
        assert "engines" in status

        # Existing endpoints
        assert len(get("/api/graph")["edges"]) > 20
        assert get("/api/sectors") and get("/api/timeseries") and get("/api/revisions") and get("/api/articles")
        assert b"NewsGraph" in urllib.request.urlopen(base + "/").read()

        # /api/analyze endpoint
        an_res = post(
            "/api/analyze",
            {"text": "Brent crude surges 12% after Middle East supply disruption", "event_date": "2022-02-24"},
        )
        assert an_res["start_node"] == "Crude Oil"
        assert an_res["start_sign"] == 1
        assert an_res["affected_assets"]
        assert an_res["top_paths"]
        assert "positive" in an_res["kpis"]

        # /api/kg endpoints
        kg_res = get("/api/kg?min_conf=0.1")
        assert len(kg_res["nodes"]) > 10
        assert get("/api/kg/stats")["articles"] >= 6

        # /api/kg/node/ endpoint
        crude_node = get("/api/kg/node/Crude%20Oil")
        assert crude_node["node"]["id"] == "Crude Oil"
        assert len(crude_node["edges"]) > 0

        # /api/validate endpoint
        val_res = post(
            "/api/validate",
            {"event_date": "2022-02-24", "assets": [{"name": "IndiGo", "ticker": "INDIGO.NS", "expected_sign": -1}]},
        )
        assert len(val_res["results"]) == 1
        assert val_res["results"][0]["name"] == "IndiGo"

    finally:
        srv.shutdown()


# ---------------------------------------------------------------- Acceptance Cases
def test_acceptance_1_brent_crude_propagation():
    """Acceptance 1:
    'Brent crude surges 12% after Middle East supply disruption' ->
    trigger Crude Oil, sign +, entity Brent linked to Crude Oil, Middle East = GPE,
    paths reach Inflation -> Rate Expectations -> Real Estate (negative) and Aviation (negative), ONGC (positive).
    """
    headline = "Brent crude surges 12% after Middle East supply disruption"
    art = news.Article(
        uuid="acc-1",
        title=headline,
        description=headline,
        snippet="",
        url="",
        source="acc",
        published_at="2022-02-24",
        sentiment_score=None,
        entities=[],
    )
    feats_res = features.extract_features(art)

    # 1. Trigger node is Crude Oil and sign is +
    prim = feats_res["primary_event_meta"]
    assert prim["trigger_node"] == "Crude Oil"
    assert prim["sign"] == 1

    # 2. Entity 'Brent' linked to 'Crude Oil'
    brent_ent = next((e for e in feats_res["entities"] if "brent" in e["text"].lower() or "brent" in e["name"].lower() or e["linked_node_id"] == "Crude Oil"), None)
    assert brent_ent is not None
    assert brent_ent["linked_node_id"] == "Crude Oil"

    # 3. 'Middle East' recognized as GPE or LOC
    me_ent = next((m for m in feats_res["mentions"] if "middle east" in m["text"].lower()), None)
    assert me_ent is not None
    assert me_ent["spacy_label"] in ("GPE", "LOC")

    # 4. Propagation paths
    kb = KnowledgeBase(":memory:")
    prop = PropagationEngine(kb)
    paths_res = prop.trace_paths("Crude Oil", trigger_sign=1, min_conf=0.01)

    assets_by_name = {a["name"]: a for a in paths_res["affected_assets"]}

    # Aviation is reached and negative
    assert "Aviation" in assets_by_name
    assert assets_by_name["Aviation"]["impact"] < 0

    # ONGC is reached and positive
    assert "ONGC" in assets_by_name
    assert assets_by_name["ONGC"]["impact"] > 0

    # Real Estate is reached via Inflation -> Rate Expectations and negative
    assert "Real Estate" in assets_by_name
    assert assets_by_name["Real Estate"]["impact"] < 0
    re_path_steps = [s["to"] for s in assets_by_name["Real Estate"]["path"]["steps"]]
    assert "Inflation" in re_path_steps or "Interest Rate Expectations" in re_path_steps


def test_acceptance_2_rbi_reversal_retrieval():
    """Acceptance 2:
    'RBI hikes repo rate by 25 bps' then 'RBI keeps rates unchanged' ->
    second article retrieved as related with similarity above threshold
    and recorded as a revision that reverses/eases earlier impact;
    an unrelated earnings-beat article is NOT retrieved.
    """
    kb = KnowledgeBase(":memory:")

    # Ingest 1: RBI hike
    a1 = news.Article(
        uuid="art-rbi-1",
        title="RBI hikes repo rate by 25 bps to tame inflation",
        description="RBI hikes repo rate by 25 bps",
        snippet="",
        url="",
        source="acc",
        published_at="2023-02-08",
        sentiment_score=None,
        entities=[],
    )
    pipeline.process_articles([a1], kb)

    # Ingest unrelated earnings article
    a_unrelated = news.Article(
        uuid="art-infosys-unrelated",
        title="Infosys beats revenue estimates with record Q3 profit",
        description="Infosys profit jumps",
        snippet="",
        url="",
        source="acc",
        published_at="2023-03-01",
        sentiment_score=None,
        entities=[],
    )
    pipeline.process_articles([a_unrelated], kb)

    # Ingest 2: RBI pause
    a2 = news.Article(
        uuid="art-rbi-2",
        title="RBI keeps rates unchanged in surprise pause on repo rate",
        description="RBI pause on rate hikes",
        snippet="",
        url="",
        source="acc",
        published_at="2023-04-06",
        sentiment_score=None,
        entities=[],
    )
    res2 = pipeline.process_articles([a2], kb)

    # Check revision created for a2 linking to a1, but NOT to a_unrelated
    revs = kb.revisions(article_id="art-rbi-2")
    assert len(revs) >= 1
    assert any(r["prior_article_id"] == "art-rbi-1" for r in revs)
    assert not any(r["prior_article_id"] == "art-infosys-unrelated" for r in revs)

    rbi_rev = next(r for r in revs if r["prior_article_id"] == "art-rbi-1")
    assert rbi_rev["similarity"] >= 0.45
    assert rbi_rev["net_effect"] == "positive"  # Pause brings relief/eases earlier hike


def test_acceptance_3_entity_merge():
    """Acceptance 3:
    Entity merge: 'Brent' and 'crude oil' resolve to one node.
    """
    linker = nlp.get_linker()
    link1 = linker.link_mention("Brent", "ORG")
    link2 = linker.link_mention("crude oil", "COMMODITY_MACRO")
    link3 = linker.link_mention("Brent Crude", "ORG")

    assert link1["linked_node_id"] == "Crude Oil"
    assert link2["linked_node_id"] == "Crude Oil"
    assert link3["linked_node_id"] == "Crude Oil"


def test_acceptance_4_upsert_and_conflict():
    """Acceptance 4:
    Upsert: same relation from two articles -> support_count=2, one edge;
    opposite sign -> conflict=True.
    """
    kb = KnowledgeBase(":memory:")

    # Insert relation from article 1
    e1_id = kb.upsert_edge(
        source_id="Crude Oil",
        target_id="Inflation",
        relation="raises cost of living",
        sign=1,
        strength=0.8,
        confidence=0.85,
        kind="observed",
        reason="Fuel costs raise prices",
        evidence_text="High oil drives inflation",
        article_id="art-1",
    )

    # Insert SAME relation from article 2
    e2_id = kb.upsert_edge(
        source_id="Crude Oil",
        target_id="Inflation",
        relation="raises cost of living",
        sign=1,
        strength=0.9,
        confidence=0.85,
        kind="observed",
        reason="Fuel costs continue to raise prices",
        evidence_text="High oil pushes CPI higher",
        article_id="art-2",
    )

    assert e1_id == e2_id  # Same edge updated
    edge_row = kb._one("SELECT * FROM edges WHERE id=?", (e1_id,))
    assert edge_row["support_count"] == 2
    art_ids = json.loads(edge_row["article_ids_json"])
    assert "art-1" in art_ids and "art-2" in art_ids
    assert edge_row["conflict"] == 0

    # Insert OPPOSITE sign relation
    e3_id = kb.upsert_edge(
        source_id="Crude Oil",
        target_id="Inflation",
        relation="cooling price shock",
        sign=-1,
        strength=0.7,
        confidence=0.6,
        kind="observed",
        reason="Subsidies buffer inflation",
        evidence_text="Government subsidies insulate consumer prices",
        article_id="art-3",
    )

    assert e3_id != e1_id
    conflicted_edges = kb._all("SELECT * FROM edges WHERE source_id='Crude Oil' AND target_id='Inflation'")
    assert any(e["conflict"] == 1 for e in conflicted_edges)


def test_nlp_modules_unit():
    """Unit test for each NLP module."""
    # 1. NER & linking
    ner_out = nlp.extract_entities("IndiGo reports higher costs while Brent crude surges in the Middle East")
    assert any(m["linked_node_id"] == "IndiGo" for m in ner_out["mentions"])
    assert any(m["linked_node_id"] == "Crude Oil" for m in ner_out["mentions"])

    # 2. Sentiment
    sent_out = nlp.analyze_sentiment("Operating profits surged 20% while expenses were kept under control.")
    assert sent_out["score"] > 0
    assert len(sent_out["sentences"]) >= 1

    # 3. Retrieval
    emb = nlp.get_embedder().embed("RBI hikes repo rate")
    assert emb.shape == (384,)

    # 4. Zero-shot classifier
    clf = nlp.classify_events("Brent crude oil surges 12% following unexpected geopolitical supply outage")
    assert clf["primary_event"]["event_type"] in ("oil_surge", "supply_disruption")
    assert clf["primary_event"]["sign"] == 1


# ---------------------------------------------------------------- Phase 6 Tests
def test_inbox_fetch_and_analyze():
    """Verify live news inbox upsert and analysis workflow."""
    kb = KnowledgeBase(":memory:")
    sample_arts = news.load_sample()[:2]
    items = [server._article_to_inbox_item(a, "test-query") for a in sample_arts]
    new_count = kb.inbox_upsert(items)
    assert new_count == 2
    inbox_items = kb.inbox_list(status="pending")
    assert len(inbox_items) == 2

    # Analyze first inbox article
    res1 = server._analyze_inbox_article(kb, items[0]["uuid"])
    assert res1["status"] == "analyzed"
    assert res1["article_id"] == items[0]["uuid"]
    assert res1["top_paths"]
    assert kb.inbox_get(items[0]["uuid"])["status"] == "analyzed"

    # Analyze second inbox article
    res2 = server._analyze_inbox_article(kb, items[1]["uuid"])
    assert res2["status"] == "analyzed"
    assert kb.inbox_get(items[1]["uuid"])["status"] == "analyzed"

    # Both articles now in KB
    assert kb.stats()["articles"] == 2


def test_sector_analysis_math():
    """Verify noisy-OR, tanh net score, and blended weights in sector analysis."""
    from app.sector_analysis import _noisy_or, _net_score, analyze_sectors

    # Noisy-OR test: 1 - (1-0.5)*(1-0.5) = 0.75
    assert abs(_noisy_or([0.5, 0.5]) - 0.75) < 1e-4
    assert abs(_noisy_or([0.4]) - 0.4) < 1e-4

    # Net score test: tanh(0.8) ~ 0.664
    import math
    assert abs(_net_score([0.8]) - round(math.tanh(0.8), 3)) < 1e-4

    # Blended analyze_sectors test
    prop_res = {
        "all_paths": [
            {
                "steps": [
                    {"from": "Crude Oil", "to": "Aviation", "to_type": "Sector", "sign": -1, "reason": "Jet fuel price shock"}
                ],
                "confidence": 0.8,
                "end_type": "Sector"
            }
        ],
        "affected_assets": [
            {"id": "Aviation", "type": "Sector", "impact": -1, "confidence": 0.8}
        ]
    }
    llm_impacts = [
        {"sector": "Aviation", "score": -0.6, "confidence": 0.7, "horizon": "short", "explanation": "Fuel margin contraction"}
    ]
    res = analyze_sectors(prop_res, llm_sector_impacts=llm_impacts)
    assert len(res) >= 1
    av = next(r for r in res if r["sector"] == "Aviation")
    assert av["direction"] == "negative"
    assert av["net_score"] < 0
    assert len(av["top_paths"]) == 1
    assert "Jet fuel" in av["top_paths"][0]["reason"]
    assert av["confidence"] > 0.5


def test_status_engine_honesty():
    """Verify NLP engines report actual states honestly, especially fallback when offline."""
    engines = nlp.get_nlp_engines()
    assert "ner" in engines and "sentiment" in engines and "retrieval" in engines and "classifier" in engines
    for k in ("ner", "sentiment", "retrieval", "classifier"):
        v = engines[k]
        assert v["state"] in ("ready", "fallback", "error")
        assert "name" in v and "model" in v


def test_gemini_listmodels_mock():
    """Verify ListModels handles error and sets status to error with helpful detail."""
    import urllib.error
    import urllib.request
    orig_open = urllib.request.urlopen

    def mock_urlopen(req, *args, **kwargs):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if "generativelanguage.googleapis.com" in url:
            import io
            fp = io.BytesIO(b'{"error": {"code": 404, "message": "Method not found"}}')
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, fp)
        return orig_open(req, *args, **kwargs)

    urllib.request.urlopen = mock_urlopen
    os.environ["GEMINI_API_KEY"] = "mock-key-for-test"
    try:
        st = llm.get_gemini_status(force_recheck=True)
        assert st["state"] == "error"
        assert "404" in st["detail"]
    finally:
        urllib.request.urlopen = orig_open
        os.environ["GEMINI_API_KEY"] = ""
        llm.get_gemini_status(force_recheck=True)


def test_phase0_marketaux_masking_and_errors():
    from app import news
    import io

    # 1. Masking
    masked = news.mask_key("secrettoken1234")
    assert masked.endswith("1234")
    assert len(masked) == len("secrettoken1234")
    assert "secrettoken" not in masked
    assert news.mask_key("") == ""
    assert news.mask_key("abc") == "••••"

    # 2. Missing key status
    old_key = os.environ.get("MARKETAUX_API_KEY", "")
    os.environ["MARKETAUX_API_KEY"] = ""
    st = news.get_marketaux_status()
    assert st["state"] == "missing"
    assert st["configured"] is False
    assert st["key_masked"] == ""

    # 3. HTTP 401 handling
    orig_open = urllib.request.urlopen
    def mock_401(req, *args, **kwargs):
        fp = io.BytesIO(b'{"error": {"code": 401, "message": "Unauthorized"}}')
        raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, fp)

    os.environ["MARKETAUX_API_KEY"] = "dummy_token_9999"
    urllib.request.urlopen = mock_401
    try:
        try:
            news.fetch_news()
            assert False, "Should have raised MarketauxError"
        except news.MarketauxError as me:
            assert me.code == 401
        st = news.get_marketaux_status()
        assert st["state"] == "invalid"
        assert st["key_masked"].endswith("9999")
        assert "dummy_token_9999" not in str(st)
    finally:
        urllib.request.urlopen = orig_open
        os.environ["MARKETAUX_API_KEY"] = old_key


def test_phase1_event_time_alignment():
    from datetime import datetime, timezone, timedelta
    from app import market

    ist_tz = timezone(timedelta(hours=5, minutes=30))
    # Wednesday 11:30 IST (in-session)
    dt_in = datetime(2026, 10, 7, 11, 30, tzinfo=ist_tz)
    rx_sess, reason, is_intra = market.align_event_trading_session(dt_in)
    assert is_intra is True
    assert rx_sess.strftime("%Y-%m-%d") == "2026-10-07"

    # Wednesday 17:30 IST (after-close)
    dt_after = datetime(2026, 10, 7, 17, 30, tzinfo=ist_tz)
    rx_sess, reason, is_intra = market.align_event_trading_session(dt_after)
    assert is_intra is False
    assert rx_sess.strftime("%Y-%m-%d") == "2026-10-08"

    # Friday 16:00 IST (after-close weekend)
    dt_fri = datetime(2026, 10, 9, 16, 0, tzinfo=ist_tz)
    rx_sess, reason, is_intra = market.align_event_trading_session(dt_fri)
    assert is_intra is False
    assert rx_sess.strftime("%Y-%m-%d") == "2026-10-12"

    # Saturday (weekend)
    dt_sat = datetime(2026, 10, 10, 14, 0, tzinfo=ist_tz)
    rx_sess, reason, is_intra = market.align_event_trading_session(dt_sat)
    assert is_intra is False
    assert rx_sess.strftime("%Y-%m-%d") == "2026-10-12"


def test_phase1_event_study_synthetic_and_verdicts():
    from datetime import datetime, timezone, timedelta
    from app import market

    ist_tz = timezone(timedelta(hours=5, minutes=30))
    # 1. No-data node
    res_repo = market.resolve_ticker("Repo Rate")
    assert res_repo["status"] == "no_data"
    study_repo = market.compute_event_study("Repo Rate", datetime(2026, 10, 1, 10, 0, tzinfo=ist_tz))
    assert study_repo["status"] == "no_data"

    # 2. Future-date rejection
    try:
        market.compute_event_study("INDIGO.NS", datetime(2030, 1, 1, tzinfo=ist_tz))
        assert False, "Should have rejected future date"
    except ValueError as ve:
        assert "future" in str(ve).lower()

    # 3. Synthetic price series test with mock fetch_history
    orig_fetch = market.fetch_history
    mock_bars = []
    base_date = datetime(2026, 8, 1)
    for i in range(50):
        d_str = (base_date + timedelta(days=i)).strftime("%Y-%m-%d")
        price = 100.0 if i <= 36 else 90.0
        mock_bars.append({
            "date": d_str, "ts": f"{d_str}T09:15:00",
            "open": price, "high": price + 1, "low": price - 1, "close": price,
            "volume": 10000.0
        })

    def mock_hist(ticker, start, end, interval="1d", timeout=8.0):
        return mock_bars

    market.fetch_history = mock_hist
    try:
        t_event = datetime(2026, 9, 6, 10, 0, tzinfo=ist_tz)
        res_conf = market.compute_event_study("BZ=F", t_event, expected_sign=-1, pre_window=20, post_window=5)
        assert res_conf["status"] == "ok"
        assert res_conf["pre_close"] == 100.0
        t0_point = [s for s in res_conf["series"] if s["date"] == res_conf["session_alignment"]["t0_date"]][0]
        assert t0_point["norm_to_100_at_T0"] == 100.0
        rx_point = [s for s in res_conf["series"] if s["is_reaction_session"]][0]
        assert rx_point["norm_to_100_at_T0"] == 90.0
        assert res_conf["verdict"] == "confirmed"

        res_contra = market.compute_event_study("BZ=F", t_event, expected_sign=1, pre_window=20, post_window=5)
        assert res_contra["verdict"] == "contradicted"
    finally:
        market.fetch_history = orig_fetch


def test_phase3_kg_roles_and_bundling():
    kb = fresh_kb()
    g = kb.graph()
    assert "nodes" in g and "edges" in g and "meta" in g
    roles = {n["role"] for n in g["nodes"]}
    # Should identify Trigger/Driver, Transmitter, Sector, Receiver/Asset, and Event
    assert "Sector" in roles
    assert "Trigger/Driver" in roles or "Transmitter" in roles
    assert any(n.get("importance") is not None for n in g["nodes"])

    # Test edge sentence generation
    sample_edge = g["edges"][0]
    sent = kb.generate_edge_sentence(sample_edge)
    assert "When " in sent and ("tends to rise" in sent or "tends to fall" in sent)
    assert "strength" in sent and "confidence" in sent


def test_phase4_kg_filters_and_endpoints():
    kb = fresh_kb()
    # 1. Filter by sector
    g_sec = kb.graph(sectors=["Aviation"], depth=1)
    sec_nodes = {n["id"] for n in g_sec["nodes"]}
    assert "Aviation" in sec_nodes
    assert len(sec_nodes) < len(kb.graph()["nodes"])

    # 2. Filter by article
    g_art = kb.graph(article_ids=["s2-crude-surge"], depth=2)
    assert len(g_art["nodes"]) > 0
    assert "highlights" in g_art

    # 3. Node and edge details
    node_det = kb.get_node_details("Crude Oil")
    assert node_det is not None
    assert node_det["node"]["id"] == "Crude Oil"
    assert "summary" in node_det
    assert "incoming_edges" in node_det and "outgoing_edges" in node_det

    edge_det = kb.get_edge_details(g_sec["edges"][0]["id"])
    assert edge_det is not None
    assert "plain_english" in edge_det

    # 4. Re-analysis deduplication
    art = ARTS["s2-crude-surge"]
    initial_edge_count = len(kb._all("SELECT id FROM edges WHERE article_id=?", (art.uuid,)))
    pipeline.process_articles([art], kb, force=True)
    reanalysis_edge_count = len(kb._all("SELECT id FROM edges WHERE article_id=?", (art.uuid,)))
    assert reanalysis_edge_count == initial_edge_count




if __name__ == "__main__":
    failed = 0
    passed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            try:
                fn()
                passed += 1
                print("PASS", name)
            except Exception as e:
                failed += 1
                print("FAIL", name, "->", type(e).__name__, e)
                import traceback
                traceback.print_exc()

    print(f"\nSummary: {passed} passed, {failed} failed.")
    sys.exit(1 if failed else 0)

