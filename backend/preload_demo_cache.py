"""
preload_demo_cache.py — Pre-populate LLM cache for 4 sample articles.  STEP 9.

Run this script ONCE before the demo to ensure the app works without live API calls:
    cd backend
    .venv\\Scripts\\python preload_demo_cache.py

This script:
  1. Reads each sample article from data/sample_news/.
  2. Computes its SHA-256 cache key.
  3. Writes a pre-defined (human-authored) realistic extraction result.

These results were constructed by a human analyst reading the articles.
They simulate what the LLM would extract and serve as fallback in demo mode.
"""

import hashlib
import json
import sys
from pathlib import Path

# Adjust path for running from backend/ directory
sys.path.insert(0, str(Path(__file__).parent))

CACHE_DIR       = Path(__file__).parent / "app" / "cache"
SAMPLE_DIR      = Path(__file__).parent.parent / "data" / "sample_news"

CACHE_DIR.mkdir(exist_ok=True)

# ── Pre-defined extraction results (human-authored) ───────────────────────────
DEMO_RESULTS = {
    "01_opec_cut.txt": {
        "event": {
            "event_type":        "OPEC+ production cut",
            "entities":          ["crude_oil", "atf", "aviation_sector", "omc_sector",
                                  "inflation_cpi", "current_account_deficit", "inr",
                                  "logistics_sector", "paint_sector", "repo_rate"],
            "direction":         "+",
            "magnitude":         "1.16 million barrels per day",
            "region":            "India+Global",
            "evidence_sentence": "OPEC+ shocked global energy markets on Sunday by announcing a voluntary production cut of approximately 1.16 million barrels per day (bpd) starting May 2023, on top of the 2 million bpd reduction agreed in October 2022.",
            "primary_node":      "crude_oil",
            "unlinked_entities": [],
        },
        "agreement_ratio": 0.95,
    },
    "02_rbi_rate_hike.txt": {
        "event": {
            "event_type":        "RBI repo rate hike",
            "entities":          ["repo_rate", "nifty_bank", "g_sec_10y", "inr",
                                  "real_estate_sector", "auto_sector", "credit_growth",
                                  "rbi_rate_expectations"],
            "direction":         "+",
            "magnitude":         "25 bps",
            "region":            "India",
            "evidence_sentence": "The Reserve Bank of India's Monetary Policy Committee (MPC) raised the benchmark repo rate by 25 basis points to 6.75% on Wednesday, in a 4-2 majority decision, signalling continued resolve to bring CPI inflation sustainably to the 4% target.",
            "primary_node":      "repo_rate",
            "unlinked_entities": [],
        },
        "agreement_ratio": 0.97,
    },
    "03_inr_depreciation.txt": {
        "event": {
            "event_type":        "INR depreciation to record low",
            "entities":          ["inr", "it_sector", "pharma_sector", "omc_sector",
                                  "current_account_deficit", "gold", "fpi_flows",
                                  "us_dollar_index"],
            "direction":         "+",
            "magnitude":         "84.50 USD/INR",
            "region":            "India",
            "evidence_sentence": "The Indian rupee touched an all-time intraday low of 84.50 against the US dollar on Friday, driven by broad dollar strength after stronger-than-expected US jobs data raised fears that the Federal Reserve would keep rates higher for longer.",
            "primary_node":      "inr",
            "unlinked_entities": [],
        },
        "agreement_ratio": 0.93,
    },
    "04_inflation_spike.txt": {
        "event": {
            "event_type":        "CPI inflation breach above RBI tolerance band",
            "entities":          ["inflation_cpi", "food_inflation", "rbi_rate_expectations",
                                  "repo_rate", "g_sec_10y", "fmcg_sector", "banking_sector",
                                  "real_estate_sector"],
            "direction":         "+",
            "magnitude":         "6.83% YoY",
            "region":            "India",
            "evidence_sentence": "India's retail inflation, measured by the Consumer Price Index (CPI), surged to 6.83% year-on-year in August 2023, breaching the Reserve Bank of India's upper tolerance band of 6% for the first time in five months, driven primarily by a spike in vegetable prices.",
            "primary_node":      "inflation_cpi",
            "unlinked_entities": [],
        },
        "agreement_ratio": 0.96,
    },
}


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def main():
    written = 0
    skipped = 0

    for filename, result in DEMO_RESULTS.items():
        article_path = SAMPLE_DIR / filename
        if not article_path.exists():
            print(f"  [WARN] Sample article not found: {article_path}")
            continue

        news_text  = article_path.read_text(encoding="utf-8")
        cache_key  = _sha256(news_text)
        cache_file = CACHE_DIR / f"{cache_key}.json"

        if cache_file.exists():
            print(f"  [SKIP] {filename} -> cache already exists ({cache_key[:12]}...)")
            skipped += 1
            continue

        cache_file.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(f"  [OK]   {filename} -> {cache_key[:12]}...  ({cache_file.name})")
        written += 1

    print(f"\nDone. {written} cache files written, {skipped} already existed.")
    print(f"Cache directory: {CACHE_DIR.resolve()}")


if __name__ == "__main__":
    main()
