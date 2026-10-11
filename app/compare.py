"""Phase 4b: compare new news with older related news and record pros/cons per sector."""
from . import llm


def _status(prior, new):
    if prior is None:
        return "new_exposure"
    d = new - prior
    if d >= 0.15:
        return "improved"
    if d <= -0.15:
        return "worsened"
    if prior * new > 0 and abs(new) >= 0.2:
        return "reinforced"
    return "unchanged"


def delta_rows(prior_scores: dict, new_impacts: list) -> list:
    rows, seen = [], set()
    for i in new_impacts:
        p, n = prior_scores.get(i["sector"]), i["score"]
        seen.add(i["sector"])
        rows.append({"sector": i["sector"], "prior": p, "new": n,
                     "delta": round(n - (p or 0.0), 3), "status": _status(p, n),
                     "reversed": p is not None and p * n < 0 and abs(p) >= 0.2 and abs(n) >= 0.2,
                     "reason": i["explanation"]})
    for sector, p in prior_scores.items():
        if sector not in seen:
            rows.append({"sector": sector, "prior": p, "new": None, "delta": None, "status": "not_mentioned",
                         "reversed": False, "reason": "Not affected in the new report."})
    return rows


def _line(r):
    p = "n/a" if r["prior"] is None else f"{r['prior']:+.2f}"
    head = f"{r['sector']}: {p} -> {r['new']:+.2f}."
    if r["reversed"]:
        head += " Reverses the earlier impact."
    elif r["status"] == "reinforced":
        head += " Continues the earlier impact."
    return f"{head} {r['reason']}"


def template_revision(new, prior, rows):
    pros, cons = [], []
    for r in rows:
        if r["new"] is None:
            continue
        if r["status"] == "improved" or (r["status"] in ("new_exposure", "reinforced") and r["new"] > 0.2):
            pros.append(_line(r))
        elif r["status"] == "worsened" or (r["status"] in ("new_exposure", "reinforced") and r["new"] < -0.2):
            cons.append(_line(r))
    net = round(sum(r["delta"] for r in rows if r["delta"] is not None), 3)
    label = "positive" if net > 0.2 else "negative" if net < -0.2 else ("mixed" if pros and cons else "neutral")
    nm = lambda rs: ", ".join(x.split(":")[0] for x in rs) or "none"  # noqa: E731
    expl = (f"Compared with the earlier news \"{prior['title']}\" ({prior['published_at'][:10]}), the new report "
            f"\"{new['title']}\" ({new['published_at'][:10]}) changes the picture as follows. "
            f"Sectors that gain: {nm(pros)}. Sectors under pressure: {nm(cons)}. "
            f"Net sector-score change is {net:+.2f}, so the overall effect is {label}.")
    return {"pros": pros, "cons": cons, "net_effect": label, "explanation": expl, "net_delta": net,
            "engine": "heuristic-rules"}


def build_revisions(kb, article, analysis, related):
    """For each related earlier article: compute sector deltas, explain, store (and link the two events)."""
    new = {"title": article.title, "published_at": article.published_at, "summary": analysis["summary"]}
    saved = []
    for prior in related:
        rows = delta_rows(prior["scores"], analysis["sector_impacts"])
        if not rows:
            continue
        rev = template_revision(new, prior, rows)
        rich = llm.enrich_comparison(new, prior, rows)
        if rich and rich["explanation"]:
            rev.update({k: rich[k] for k in ("pros", "cons", "explanation", "engine")})
            if rich["net_effect"]:
                rev["net_effect"] = rich["net_effect"]
        rev.update({"article_id": article.uuid, "prior_article_id": prior["id"], "family": prior.get("family", ""),
                    "similarity": float(prior.get("similarity", 0.0)),
                    "deltas": rows, "reversed": any(r["reversed"] for r in rows)})
        kb.save_revision(rev)
        saved.append(rev)
    return saved
