"""Named Entity Recognition using spaCy + Canonical Entity Linking."""
import os
import re
from typing import Any, Dict, List, Optional

from .base import cached_result, get_device, get_mock
from .linking import LABEL_TYPE_MAP, get_linker

TARGET_SPACY_LABELS = {"ORG", "GPE", "LOC", "PERSON", "MONEY", "PERCENT", "QUANTITY", "DATE"}

_SPACY_NLP = None
_MODEL_NAME = None


def get_spacy_model_name() -> str:
    return os.getenv("NEWSGRAPH_SPACY_MODEL", "en_core_web_sm").strip()


def get_spacy_nlp():
    global _SPACY_NLP, _MODEL_NAME
    mock = get_mock("spacy")
    if mock is not None:
        return mock

    target_model = get_spacy_model_name()
    if _SPACY_NLP is not None and _MODEL_NAME == target_model:
        return _SPACY_NLP

    try:
        import spacy
        try:
            _SPACY_NLP = spacy.load(target_model)
            _MODEL_NAME = target_model
            return _SPACY_NLP
        except OSError:
            # Model not found: give clear hint
            raise RuntimeError(
                f"spaCy model '{target_model}' is not installed. "
                f"Please run: python -m spacy download {target_model}"
            )
    except ImportError:
        raise RuntimeError("spacy is not installed. Please run: pip install spacy")


def extract_entities(text: str, embedder=None) -> Dict[str, Any]:
    """Run spaCy NER and Entity Linking on input text."""
    mock = get_mock("ner_extractor")
    if mock is not None:
        return mock(text)

    def _compute():
        model_name = get_spacy_model_name()
        try:
            nlp = get_spacy_nlp()
        except RuntimeError as e:
            # If spaCy model missing or mock fallback needed:
            return _fallback_ner(text, str(e))

        doc = nlp(text)
        linker = get_linker()
        mentions = []

        for ent in doc.ents:
            if ent.label_ not in TARGET_SPACY_LABELS:
                continue
            link_info = linker.link_mention(ent.text, ent.label_, embedder=embedder)
            mentions.append({
                "text": ent.text,
                "start_char": ent.start_char,
                "end_char": ent.end_char,
                "spacy_label": ent.label_,
                "linked_node_id": link_info["linked_node_id"],
                "node_type": link_info["node_type"],
                "link_score": link_info["link_score"],
                "linked": link_info["linked"],
                "ticker": link_info.get("ticker"),
            })

        # Also extract known commodities / indicators directly if missed by spaCy
        found_nodes = {m["linked_node_id"] for m in mentions if m["linked"]}
        text_lower = text.lower()
        sorted_aliases = sorted(linker.alias_map.items(), key=lambda x: len(x[0]), reverse=True)
        for alias, canon_id in sorted_aliases:
            if canon_id not in found_nodes and re.search(r"\b" + re.escape(alias) + r"\b", text_lower):
                m = re.search(r"\b" + re.escape(alias) + r"\b", text_lower)
                if m:
                    node = linker.nodes.get(canon_id, {})
                    mentions.append({
                        "text": text[m.start():m.end()],
                        "start_char": m.start(),
                        "end_char": m.end(),
                        "spacy_label": "COMMODITY_MACRO",
                        "linked_node_id": canon_id,
                        "node_type": node.get("type", "Commodity"),
                        "link_score": 1.0,
                        "linked": True,
                        "ticker": node.get("ticker"),
                    })
                    found_nodes.add(canon_id)

        return {
            "mentions": mentions,
            "engine": f"spacy:{model_name}",
        }

    return cached_result("spacy_ner", text, _compute)


def _fallback_ner(text: str, reason: str) -> Dict[str, Any]:
    """Lightweight fallback when spaCy model is not yet downloaded."""
    linker = get_linker()
    mentions = []
    text_lower = text.lower()
    for alias, canon_id in linker.alias_map.items():
        m = re.search(r"\b" + re.escape(alias) + r"\b", text_lower)
        if m:
            node = linker.nodes.get(canon_id, {})
            mentions.append({
                "text": text[m.start():m.end()],
                "start_char": m.start(),
                "end_char": m.end(),
                "spacy_label": "ORG" if node.get("type") == "Company" else "GPE",
                "linked_node_id": canon_id,
                "node_type": node.get("type", "Company"),
                "link_score": 1.0,
                "linked": True,
                "ticker": node.get("ticker"),
            })
    return {
        "mentions": mentions,
        "engine": f"fallback_ner ({reason})",
    }
