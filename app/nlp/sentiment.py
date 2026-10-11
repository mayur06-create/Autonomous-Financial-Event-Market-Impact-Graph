"""Financial sentiment analysis using FinBERT (ProsusAI/finbert).

Scores sentences (pos, neg, neutral), computes length-weighted article score,
and computes per-entity sentiment from sentences containing each entity.
NOTE: Sentiment is NEVER used as the event direction.
"""
import os
import re
from typing import Any, Dict, List, Optional

from .base import cached_result, get_device, get_mock

_FINBERT_PIPELINE = None
_MODEL_NAME = "ProsusAI/finbert"


def _split_sentences(text: str) -> List[str]:
    # Simple, robust sentence boundary split
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    return [s.strip() for s in sentences if len(s.strip()) > 3]


def get_finbert_pipeline():
    global _FINBERT_PIPELINE
    mock = get_mock("finbert")
    if mock is not None:
        return mock

    if _FINBERT_PIPELINE is not None:
        return _FINBERT_PIPELINE

    try:
        from transformers import AutoModelForSequenceClassification, AutoTokenizer, pipeline
        device = 0 if get_device() == "cuda" else -1
        tokenizer = AutoTokenizer.from_pretrained(_MODEL_NAME)
        model = AutoModelForSequenceClassification.from_pretrained(_MODEL_NAME)
        _FINBERT_PIPELINE = pipeline(
            "text-classification",
            model=model,
            tokenizer=tokenizer,
            top_k=None,
            device=device,
        )
        return _FINBERT_PIPELINE
    except ImportError:
        raise RuntimeError("transformers and torch are required for FinBERT. Run: pip install transformers torch")
    except Exception as e:
        raise RuntimeError(f"Failed to load FinBERT model '{_MODEL_NAME}': {e}. Ensure internet access or pre-download.")


def analyze_sentiment(text: str, entities: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Analyze article sentiment using FinBERT with per-sentence and per-entity aggregation."""
    mock = get_mock("sentiment_analyzer")
    if mock is not None:
        return mock(text, entities)

    def _compute():
        sentences = _split_sentences(text)
        if not sentences:
            sentences = [text.strip() or "Market update."]

        if os.getenv("NEWSGRAPH_OFFLINE") == "1":
            return _heuristic_sentiment_fallback(sentences, entities, "NEWSGRAPH_OFFLINE=1")

        try:
            pipe = get_finbert_pipeline()
            # Batch inference over sentences
            outputs = pipe(sentences, truncation=True, max_length=512)
            engine = f"finbert:{_MODEL_NAME}"
        except Exception as e:
            # Fallback for offline / download pending environments
            return _heuristic_sentiment_fallback(sentences, entities, str(e))

        sentence_scores = []
        total_len = 0
        weighted_sum = 0.0

        for sent, res in zip(sentences, outputs):
            # res is list of {'label': 'positive'|'negative'|'neutral', 'score': float}
            prob_map = {item["label"].lower(): float(item["score"]) for item in res}
            pos = prob_map.get("positive", 0.0)
            neg = prob_map.get("negative", 0.0)
            neu = prob_map.get("neutral", 0.0)
            score = pos - neg
            s_len = max(1, len(sent.split()))

            sentence_scores.append({
                "sentence": sent,
                "score": round(score, 3),
                "positive": round(pos, 3),
                "negative": round(neg, 3),
                "neutral": round(neu, 3),
                "length": s_len,
            })
            weighted_sum += score * s_len
            total_len += s_len

        article_score = round(weighted_sum / max(1, total_len), 3)

        # Per-entity sentiment
        entity_sentiments = {}
        if entities:
            for ent in entities:
                ent_name = ent.get("linked_node_id") or ent.get("name") or ent.get("text")
                if not ent_name:
                    continue
                ent_pattern = re.compile(r"\b" + re.escape(ent.get("text", ent_name)) + r"\b", re.I)
                ent_sentences = [s for s in sentence_scores if ent_pattern.search(s["sentence"])]
                if ent_sentences:
                    ent_wt = sum(s["score"] * s["length"] for s in ent_sentences)
                    ent_tot = sum(s["length"] for s in ent_sentences)
                    entity_sentiments[ent_name] = round(ent_wt / max(1, ent_tot), 3)
                else:
                    entity_sentiments[ent_name] = article_score

        return {
            "score": article_score,
            "sentences": sentence_scores,
            "entity_sentiment": entity_sentiments,
            "engine": engine,
        }

    return cached_result("finbert_sentiment", text, _compute)


def _heuristic_sentiment_fallback(sentences: List[str], entities: Optional[List[Dict[str, Any]]], reason: str) -> Dict[str, Any]:
    """Lightweight fallback when FinBERT weights are not yet cached."""
    # Simple neutral fallback with basic financial signals
    sentence_scores = []
    for s in sentences:
        low = s.lower()
        pos = sum(1 for w in ["gain", "rise", "surge", "beat", "rally", "profit", "jump"] if w in low)
        neg = sum(1 for w in ["fall", "slump", "miss", "loss", "decline", "cut", "drop", "pressure"] if w in low)
        score = (pos - neg) / max(1, pos + neg) if (pos or neg) else 0.0
        sentence_scores.append({
            "sentence": s,
            "score": round(score, 3),
            "positive": round(max(0.0, score), 3),
            "negative": round(max(0.0, -score), 3),
            "neutral": 0.5,
            "length": len(s.split()),
        })

    avg_score = round(sum(s["score"] for s in sentence_scores) / max(1, len(sentence_scores)), 3)
    entity_sents = {}
    if entities:
        for ent in entities:
            name = ent.get("linked_node_id") or ent.get("name") or ent.get("text")
            if name:
                entity_sents[name] = avg_score

    return {
        "score": avg_score,
        "sentences": sentence_scores,
        "entity_sentiment": entity_sents,
        "engine": f"fallback_sentiment ({reason})",
    }
