"""NLP package for NewsGraph: spaCy NER + Entity Linking, FinBERT sentiment,
MiniLM sentence embeddings, and DeBERTa/BART zero-shot classification.
"""
import os

from .base import clear_mocks, get_device, register_mock
from .classifier import LABEL_EVENT_MAP, classify_events, get_zeroshot_model_name
from .linking import EntityLinker, get_linker
from .ner import extract_entities, get_spacy_model_name
from .retrieval import (
    MiniLMEmbedder,
    cosine_similarity,
    embed_article,
    find_similar_articles,
    get_embedder,
    prepare_retrieval_text,
)
from .sentiment import analyze_sentiment


def _probe_spacy() -> dict:
    if os.getenv("NEWSGRAPH_OFFLINE") == "1":
        return {"name": "spaCy", "model": get_spacy_model_name(), "state": "fallback",
                "detail": "NEWSGRAPH_OFFLINE=1 — using rule-based tokenizer"}
    try:
        import spacy
        model = get_spacy_model_name()
        installed = spacy.util.get_installed_models()
        if model in installed:
            return {"name": "spaCy", "model": model, "state": "ready", "detail": ""}
        return {"name": "spaCy", "model": model, "state": "fallback",
                "detail": f"Model not installed — run: python -m spacy download {model}"}
    except Exception as e:
        return {"name": "spaCy", "model": get_spacy_model_name(), "state": "fallback", "detail": str(e)[:150]}


def _probe_finbert() -> dict:
    if os.getenv("NEWSGRAPH_OFFLINE") == "1":
        return {"name": "FinBERT", "model": "ProsusAI/finbert", "state": "fallback",
                "detail": "NEWSGRAPH_OFFLINE=1 — using heuristic fallback"}
    try:
        from .sentiment import _FINBERT_PIPELINE
        if _FINBERT_PIPELINE is not None:
            return {"name": "FinBERT", "model": "ProsusAI/finbert", "state": "ready", "detail": ""}
        from transformers import AutoModelForSequenceClassification
        AutoModelForSequenceClassification.from_pretrained("ProsusAI/finbert", local_files_only=True)
        return {"name": "FinBERT", "model": "ProsusAI/finbert", "state": "ready", "detail": ""}
    except Exception:
        return {"name": "FinBERT", "model": "ProsusAI/finbert", "state": "fallback",
                "detail": "Model not downloaded locally — run: python -m app.nlp.download"}


def _probe_minilm() -> dict:
    if os.getenv("NEWSGRAPH_OFFLINE") == "1":
        return {"name": "MiniLM", "model": "all-MiniLM-L6-v2", "state": "fallback",
                "detail": "NEWSGRAPH_OFFLINE=1 — using BoW pseudo-embeddings"}
    try:
        from .retrieval import _MINILM_MODEL
        if _MINILM_MODEL is not None:
            return {"name": "MiniLM", "model": "all-MiniLM-L6-v2", "state": "ready", "detail": ""}
        from sentence_transformers import SentenceTransformer
        SentenceTransformer("all-MiniLM-L6-v2", local_files_only=True)
        return {"name": "MiniLM", "model": "all-MiniLM-L6-v2", "state": "ready", "detail": ""}
    except Exception:
        return {"name": "MiniLM", "model": "all-MiniLM-L6-v2", "state": "fallback",
                "detail": "Model not downloaded locally — run: python -m app.nlp.download"}


def _probe_classifier() -> dict:
    model = get_zeroshot_model_name()
    if os.getenv("NEWSGRAPH_OFFLINE") == "1":
        return {"name": "Classifier", "model": model, "state": "fallback",
                "detail": "NEWSGRAPH_OFFLINE=1 — using keyword-rule fallback"}
    try:
        from .classifier import _ZEROSHOT_PIPELINE
        if _ZEROSHOT_PIPELINE is not None:
            return {"name": "Classifier", "model": model, "state": "ready", "detail": ""}
        from transformers import AutoModelForSequenceClassification
        AutoModelForSequenceClassification.from_pretrained(model, local_files_only=True)
        return {"name": "Classifier", "model": model, "state": "ready", "detail": ""}
    except Exception:
        return {"name": "Classifier", "model": model, "state": "fallback",
                "detail": f"Model not downloaded locally — run: python -m app.nlp.download"}


# Cache probes so status is fast after first call
_ENGINE_CACHE: dict = {}


def get_nlp_engines(force: bool = False) -> dict:
    """Return dict of engine status objects {name, model, state, detail}."""
    global _ENGINE_CACHE
    if _ENGINE_CACHE and not force:
        return _ENGINE_CACHE
    _ENGINE_CACHE = {
        "ner":        _probe_spacy(),
        "sentiment":  _probe_finbert(),
        "retrieval":  _probe_minilm(),
        "classifier": _probe_classifier(),
        "device":     get_device(),
    }
    return _ENGINE_CACHE


__all__ = [
    "extract_entities",
    "analyze_sentiment",
    "classify_events",
    "get_embedder",
    "embed_article",
    "find_similar_articles",
    "prepare_retrieval_text",
    "cosine_similarity",
    "EntityLinker",
    "get_linker",
    "register_mock",
    "clear_mocks",
    "get_nlp_engines",
    "LABEL_EVENT_MAP",
]
