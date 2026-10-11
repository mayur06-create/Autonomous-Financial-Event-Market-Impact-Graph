"""Tokenization, TF-IDF, and modern NLP feature extraction.
Uses spaCy NER + Entity Linking, FinBERT sentiment, and zero-shot event classification.
"""
import math
import os
import re
from collections import Counter
from typing import Any, Dict, List, Optional

from . import nlp, rules

STOPWORDS = frozenset("""a about after again all also am an and any are as at be because been before being between
both but by can could did do does doing during each few for from further had has have having he her here him his how
i if in into is it its just me more most my no nor not of off on once only or other our out own same she should so
some such than that the their them then there these they this those through to too until very was we were what when
where which while who whom why will with would you your said says say""".split())

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9+&'\-]*|\d+(?:\.\d+)?%?")
_NUM_RE = re.compile(
    r"(\$\s?\d+(?:[.,]\d+)?\s?(?:bn|billion|million|mn|trillion)?"
    r"|\d+(?:\.\d+)?\s?(?:%|bps|basis points|per cent|bn|billion|million|crore|lakh))", re.I)


def clean_text(text: str) -> str:
    text = re.sub(r"https?://\S+", " ", text or "")
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def tokenize(text: str):
    toks = [t.lower().strip("'-") for t in _TOKEN_RE.findall(clean_text(text))]
    return [t for t in toks if len(t) > 1 and t not in STOPWORDS]


def stem(w: str) -> str:
    if len(w) <= 3 or w.isdigit() or "%" in w:
        return w
    if w.endswith("ies") and len(w) > 4:
        return w[:-3] + "y"
    for suf in ("ingly", "ing", "edly", "ed"):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            return w[:-len(suf)]
    if w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def build_idf(docs_tokens):
    n = len(docs_tokens)
    df = Counter()
    for toks in docs_tokens:
        df.update({stem(t) for t in toks})
    return {t: math.log((1 + n) / (1 + c)) + 1.0 for t, c in df.items()}


def top_keywords(tokens, idf=None, k=8):
    stems = [stem(t) for t in tokens]
    surface = {}
    for t, s in zip(tokens, stems):
        surface.setdefault(s, Counter())[t] += 1
    tf = Counter(stems)
    first = {}
    for i, s in enumerate(stems):
        first.setdefault(s, i)
    ranked = sorted(tf, key=lambda s: (-(tf[s] * (idf or {}).get(s, 1.0) + (0.2 if not s.isdigit() else -1)), first[s]))
    return [{"keyword": surface[s].most_common(1)[0][0], "score": round(tf[s] * (idf or {}).get(s, 1.0), 3)}
            for s in ranked if not s.isdigit()][:k]


def top_bigrams(tokens, k=8):
    c = Counter(zip(tokens, tokens[1:]))
    first = {}
    for i, bg in enumerate(zip(tokens, tokens[1:])):
        first.setdefault(bg, i)
    ranked = sorted(c, key=lambda b: (-c[b], first[b]))
    return [" ".join(b) for b in ranked if not any(x.isdigit() for x in b)][:k]


def extract_numbers(text):
    seen, out = set(), []
    for m in _NUM_RE.findall(text):
        m = m.strip()
        if m.lower() not in seen:
            seen.add(m.lower())
            out.append(m)
    return out


def detect_sectors(article, entities):
    scores = Counter()
    for s, rx in rules.SECTOR_RE.items():
        scores[s] += 2 * len(rx.findall(article.title)) + len(rx.findall(article.description)) \
                     + len(rx.findall(article.snippet))
    for e in entities:
        sec = e.get("sector")
        if sec:
            scores[sec] += 1
    return [{"sector": s, "relevance": round(min(1.0, c / 4), 2), "mentions": c}
            for s, c in scores.most_common() if c > 0]


def extract_features(article, idf=None) -> dict:
    text = clean_text(article.text)
    tokens = tokenize(text)

    # 1. spaCy NER + Canonical Entity Linking
    ner_res = nlp.extract_entities(text)
    raw_mentions = ner_res.get("mentions", [])

    # Format entities for graph and downstream reasoning
    ents_map = {}
    for m in raw_mentions:
        nid = m.get("linked_node_id") or m["text"]
        norm_key = nid.lower()
        sec = rules.sector_for_name(nid) or rules.sector_for_name(m["text"])
        if norm_key not in ents_map or (m.get("link_score", 0) > ents_map[norm_key].get("link_score", 0)):
            ents_map[norm_key] = {
                "name": nid,
                "text": m["text"],
                "type": m.get("node_type", "Company").lower(),
                "node_type": m.get("node_type", "Company"),
                "spacy_label": m.get("spacy_label", "ORG"),
                "linked_node_id": nid,
                "link_score": m.get("link_score", 1.0),
                "linked": m.get("linked", True),
                "ticker": m.get("ticker"),
                "sector": sec,
                "span": (m.get("start_char", 0), m.get("end_char", 0)),
                "source": "spacy",
            }

    # Add any Marketaux metadata entities if present
    for me in getattr(article, "entities", []) or []:
        if me.get("name"):
            key = me["name"].lower()
            if key not in ents_map:
                ents_map[key] = {
                    "name": me["name"],
                    "text": me["name"],
                    "type": "company",
                    "node_type": "Company",
                    "spacy_label": "ORG",
                    "linked_node_id": me["name"],
                    "link_score": 1.0,
                    "linked": True,
                    "ticker": me.get("symbol"),
                    "sector": rules.sector_for_name(me["name"]) or rules.INDUSTRY_MAP.get(me.get("industry")),
                    "source": "marketaux",
                }

    ents = list(ents_map.values())

    # 2. FinBERT Sentiment (per-sentence & per-entity)
    sent_res = nlp.analyze_sentiment(text, entities=ents)
    # Attach entity sentiment scores
    for e in ents:
        ent_key = e["name"]
        e["sentiment"] = sent_res.get("entity_sentiment", {}).get(ent_key, sent_res.get("score", 0.0))

    # 3. Zero-shot Directional Event Classification
    clf_res = nlp.classify_events(text)
    events = clf_res.get("events", [])
    primary_ev = clf_res.get("primary_event")

    # 4. Sector relevance
    sectors = detect_sectors(article, ents)

    return {
        "n_tokens": len(tokens),
        "tokens": tokens,
        "bigrams": top_bigrams(tokens),
        "keywords": top_keywords(tokens, idf),
        "entities": ents,
        "mentions": raw_mentions,
        "sectors": sectors,
        "events": events,
        "primary_event": primary_ev["event_type"] if primary_ev else (events[0]["event_type"] if events else None),
        "primary_event_meta": primary_ev or (events[0] if events else None),
        "numbers": extract_numbers(text),
        "sentiment": sent_res,
        "models": {
            "ner": ner_res.get("engine", "spacy:en_core_web_sm"),
            "sentiment": sent_res.get("engine", "finbert:ProsusAI/finbert"),
            "classifier": clf_res.get("engine", "zeroshot:MoritzLaurer/deberta-v3-base-zeroshot-v2.0"),
            "retrieval": "sentence-transformers:all-MiniLM-L6-v2",
        },
    }
