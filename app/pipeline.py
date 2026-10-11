"""Orchestrates the full flow: news -> features -> relations (Gemini) -> KB -> comparison with older news."""
from . import compare, features, llm, news, nlp


def process_articles(articles, kb, force=False):
    arts = sorted(articles, key=lambda a: a.published_at)  # oldest first, so newer news compares to older
    idf = features.build_idf([features.tokenize(a.text) for a in arts])
    results = []
    for a in arts:
        if kb.has_article(a.uuid):
            if not force:
                results.append({"id": a.uuid, "title": a.title, "status": "skipped (already in knowledge base)"})
                continue
            kb.delete_article(a.uuid)

        # 1. Feature extraction (spaCy, FinBERT, zero-shot classifier)
        feats = features.extract_features(a, idf)

        # 2. Embedding & Related-news retrieval via cosine similarity
        emb = nlp.embed_article(a.title, a.text)
        related = kb.find_related(emb, a.published_at, exclude_id=a.uuid)

        # 3. Relationship reasoning with Gemini or rule fallback
        analysis = llm.analyze(a, feats, related)

        # 4. Save analysis to knowledge base
        kb.save_analysis(a, feats, analysis, embedding=emb)

        # 5. Build and save revisions (with similarity scores)
        revs = compare.build_revisions(kb, a, analysis, related)

        results.append({
            "id": a.uuid,
            "title": a.title,
            "status": "processed",
            "engine": analysis["engine"],
            "events": [e.get("label", e.get("type", "")) for e in feats["events"]],
            "sectors": {i["sector"]: i["score"] for i in analysis["sector_impacts"]},
            "compared_with": [r["prior_article_id"] for r in revs],
            "models": feats.get("models"),
        })
    return results


def run_ingest(kb, mode="sample", force=False, **opts):
    if mode == "live":
        arts = news.fetch_news(
            search=opts.get("search"),
            symbols=opts.get("symbols"),
            industries=opts.get("industries"),
            limit=int(opts.get("limit") or 10),
            pages=int(opts.get("pages") or 1),
        )
    else:
        arts = news.load_sample()
    return {"fetched": len(arts), "results": process_articles(arts, kb, force=force)}
