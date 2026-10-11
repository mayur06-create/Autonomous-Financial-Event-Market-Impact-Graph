import os
import sys
import time
import json
import urllib.request
import urllib.error

# Ensure app is in path
sys.path.insert(0, os.path.abspath("."))

from app import config, news, nlp, features, llm, kb as kb_module, propagate, sector_analysis
from app.kb import KnowledgeBase
from app.propagate import PropagationEngine, validate_asset_event_study
from app.sector_analysis import analyze_sectors

TEST_ARTICLES = [
    "RBI tightens daily cash reserve rules as banking system liquidity stays elevated",
    "RBI OMO sale fears spur bond sell-off; 10-year G-Sec hits three year high",
    "Nifty bulls regain momentum, but can bears strike back? 5 factors to decide D-Street's fate next week"
]

print("=" * 80)
print("PHASE 0: INVESTIGATION AND ROOT CAUSE ANALYSIS")
print("=" * 80)

# Check Gemini status directly
print("\n[HYPOTHESIS A CHECK]: Testing Gemini Key and Endpoint...")
gemini_key = config.gemini_key()
print(f"Gemini Key present: {bool(gemini_key)}, starts with: {gemini_key[:8] if gemini_key else 'None'}...")
t0 = time.time()
gemini_status = llm.get_gemini_status(force_recheck=True)
gemini_probe_time = time.time() - t0
print(f"Gemini probe status: {gemini_status} (took {gemini_probe_time:.2f}s)")

# Test call_gemini directly to see error & latency
t0 = time.time()
gemini_call_error = None
try:
    llm._call_gemini("Say 'OK' in JSON format: {\"status\": \"OK\"}", retries=0)
    gemini_call_time = time.time() - t0
    print(f"Gemini call succeeded in {gemini_call_time:.2f}s")
except Exception as e:
    gemini_call_time = time.time() - t0
    gemini_call_error = str(e)
    print(f"Gemini call failed with error: {e} (took {gemini_call_time:.2f}s with 0 retries)")

print("\n" + "=" * 80)
print("PER-STAGE TIMINGS AND PIPELINE REPRODUCTION")
print("=" * 80)

kb = KnowledgeBase(":memory:")

for idx, headline in enumerate(TEST_ARTICLES, 1):
    print(f"\n--- Article {idx}: \"{headline}\" ---")
    timings = {}
    
    # 1. Fetch / Article creation
    t0 = time.time()
    art = news.Article(
        uuid=f"test-art-{idx}",
        title=headline,
        description=headline,
        snippet="",
        url=f"http://example.com/{idx}",
        source="wire",
        published_at="2024-03-15",
        sentiment_score=None,
        entities=[]
    )
    timings["fetch"] = time.time() - t0
    
    # 2. NER & Linking
    t0 = time.time()
    ner_res = nlp.extract_entities(art.text)
    timings["ner_and_link"] = time.time() - t0
    
    # 3. Sentiment
    t0 = time.time()
    sent_res = nlp.analyze_sentiment(art.text)
    timings["sentiment"] = time.time() - t0
    
    # 4. Zero-shot event classification
    t0 = time.time()
    zero_res = nlp.classify_events(art.text)
    timings["zero_shot"] = time.time() - t0
    
    # Features extraction
    t0 = time.time()
    feats = features.extract_features(art)
    timings["features_total"] = time.time() - t0
    
    # 5. Embedding & Related news
    t0 = time.time()
    emb = nlp.embed_article(art.title, art.text)
    related = kb.find_related(emb, art.published_at, exclude_id=art.uuid)
    timings["embedding_related"] = time.time() - t0
    
    # 6. Gemini / LLM Relations
    t0 = time.time()
    analysis = llm.analyze(art, feats, related)
    timings["llm_relations"] = time.time() - t0
    
    # 7. KG Upsert
    t0 = time.time()
    kb.save_analysis(art, feats, analysis, embedding=emb)
    timings["kg_upsert"] = time.time() - t0
    
    # 8. Propagation
    t0 = time.time()
    primary_ev = feats.get("primary_event_meta")
    trig_node = (primary_ev or {}).get("trigger_node")
    if not trig_node:
        for e in feats.get("entities", []):
            if e.get("node_type") in ("Commodity", "Indicator", "Currency", "Sector"):
                trig_node = e.get("linked_node_id")
                break
    trig_fallback_used = False
    if not trig_node:
        trig_fallback_used = True
        trig_node = "Crude Oil" if "oil" in headline.lower() or "brent" in headline.lower() else "Inflation"
    
    trig_sign = (primary_ev or {}).get("sign", 1) if primary_ev else 1
    
    prop = PropagationEngine(kb)
    prop_res = prop.trace_paths(trig_node, trig_sign, min_conf=0.05, as_of_date=art.published_at)
    timings["propagation"] = time.time() - t0
    
    # 9. Sector Analysis
    t0 = time.time()
    sector_res = analyze_sectors(
        prop_res,
        llm_sector_impacts=analysis.get("sector_impacts", []),
        article_id=art.uuid
    )
    timings["sector_analysis"] = time.time() - t0
    
    # 10. Validation (test on 1 asset with yfinance)
    t0 = time.time()
    top_assets = (prop_res.get("affected_assets") or [])[:2]
    val_results = []
    for asset in top_assets:
        try:
            val_results.append(validate_asset_event_study(asset.get("ticker"), art.published_at, expected_sign=asset.get("impact", 1)))
        except Exception as e:
            val_results.append({"error": str(e)})
    timings["validation"] = time.time() - t0
    
    print("Stage Timings:")
    total_time = sum(timings.values())
    for stage, sec in timings.items():
        print(f"  - {stage:20s}: {sec:6.3f}s ({sec/total_time*100:4.1f}%)")
    print(f"  TOTAL: {total_time:.3f}s")
    
    print(f"Trigger Identified: '{trig_node}' (fallback used: {trig_fallback_used})")
    print(f"Zero-shot primary event: {zero_res.get('primary_event')}")
    print(f"Chains Traced: {len(prop_res.get('top_paths', []))}, Affected Assets: {len(prop_res.get('affected_assets', []))}")
    print(f"Sectors impacted: {[s['sector'] for s in sector_res]}")

print("\n[HYPOTHESIS F CHECK]: Testing yfinance without ticker / network...")
t0 = time.time()
try:
    v = validate_asset_event_study("NONEXISTENT.NS", "2024-03-15", expected_sign=1)
    print(f"yfinance call took {time.time() - t0:.2f}s, result: {v}")
except Exception as e:
    print(f"yfinance call failed after {time.time() - t0:.2f}s: {e}")
