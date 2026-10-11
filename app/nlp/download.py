"""Model download checker and pre-loader for NewsGraph NLP engines.

Run: python -m app.nlp.download
Downloads: spaCy en_core_web_sm, ProsusAI/finbert, all-MiniLM-L6-v2,
           MoritzLaurer/deberta-v3-base-zeroshot-v2.0
"""
import sys
import os

MODELS = [
    ("spaCy", "spacy", None),
    ("FinBERT", "transformers", "ProsusAI/finbert"),
    ("MiniLM", "sentence_transformers", "sentence-transformers/all-MiniLM-L6-v2"),
    ("DeBERTa-v3 zero-shot", "transformers", "MoritzLaurer/deberta-v3-base-zeroshot-v2.0"),
]

_OK   = "\033[92mOK\033[0m"
_FAIL = "\033[91mFAIL\033[0m"
_SKIP = "\033[93mSKIP\033[0m"


def _check_spacy():
    try:
        import subprocess, sys
        import spacy
        try:
            spacy.load("en_core_web_sm")
            return True, "loaded en_core_web_sm"
        except OSError:
            print("  → downloading en_core_web_sm …", flush=True)
            r = subprocess.run(
                [sys.executable, "-m", "spacy", "download", "en_core_web_sm"],
                capture_output=True, text=True
            )
            if r.returncode == 0:
                return True, "downloaded en_core_web_sm"
            return False, r.stderr.strip()[:200]
    except ImportError as e:
        return False, f"spacy not installed: {e}"


def _check_hf(model_name, pipeline_task):
    try:
        from transformers import AutoTokenizer, AutoModelForSequenceClassification
        AutoTokenizer.from_pretrained(model_name)
        AutoModelForSequenceClassification.from_pretrained(model_name)
        return True, f"loaded {model_name}"
    except Exception as e:
        return False, str(e)[:200]


def _check_minilm(model_name):
    try:
        from sentence_transformers import SentenceTransformer
        SentenceTransformer(model_name)
        return True, f"loaded {model_name}"
    except Exception as e:
        return False, str(e)[:200]


def main():
    print("NewsGraph — NLP model pre-download & health check\n")
    all_ok = True

    # spaCy
    print("[ 1/4 ] spaCy en_core_web_sm …", flush=True)
    ok, msg = _check_spacy()
    print(f"        {_OK if ok else _FAIL}  {msg}")
    all_ok = all_ok and ok

    # FinBERT
    print("[ 2/4 ] FinBERT (ProsusAI/finbert) …", flush=True)
    ok, msg = _check_hf("ProsusAI/finbert", "text-classification")
    print(f"        {_OK if ok else _FAIL}  {msg}")
    all_ok = all_ok and ok

    # MiniLM
    print("[ 3/4 ] MiniLM (all-MiniLM-L6-v2) …", flush=True)
    ok, msg = _check_minilm("sentence-transformers/all-MiniLM-L6-v2")
    print(f"        {_OK if ok else _FAIL}  {msg}")
    all_ok = all_ok and ok

    # DeBERTa zero-shot
    print("[ 4/4 ] DeBERTa-v3 zero-shot …", flush=True)
    ok, msg = _check_hf("MoritzLaurer/deberta-v3-base-zeroshot-v2.0", "zero-shot-classification")
    print(f"        {_OK if ok else _FAIL}  {msg}")
    all_ok = all_ok and ok

    print()
    if all_ok:
        print("All models ready. Run: python -m app serve")
    else:
        print("Some models failed. Check errors above.")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
