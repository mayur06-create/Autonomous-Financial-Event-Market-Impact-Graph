"""
backtest.py — Historical event backtest for Market Impact Graph.  STEP 10.

Tests 10 historical Indian macro events.
For each event:
  1. Runs propagation on the seed graph (NO LLM needed — event nodes are hand-specified).
  2. Gets the top-5 predicted affected assets with direction.
  3. Downloads actual market returns from yfinance for a ±3 day event window.
  4. Computes hit rate: % of (asset, direction) pairs where prediction was correct.

IMPORTANT: Only numbers actually computed by this script are reported.
           No results are hard-coded or invented.

Run:
    cd backend
    .venv\\Scripts\\python backtest.py

Output: CSV + summary table printed to stdout.
"""

import sys
import json
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
logging.basicConfig(level=logging.WARNING)  # suppress debug noise

from app.schemas import ExtractedEvent, Sign
from app.propagation import propagate
from app.validation import run_event_study


# ── Define 10 historical events ───────────────────────────────────────────────
# Each event specifies: which seed node is triggered, direction, and event date.
# Dates are approximate — the actual market reaction may lag 1-2 days.

@dataclass
class HistoricalEvent:
    name:         str
    primary_node: str
    direction:    Sign
    event_date:   str   # YYYY-MM-DD (approximate date of news impact)
    notes:        str   = ""


HISTORICAL_EVENTS = [
    HistoricalEvent(
        name         = "OPEC+ 2Mbpd Cut (Oct 2022)",
        primary_node = "crude_oil",
        direction    = Sign.positive,
        event_date   = "2022-10-05",
        notes        = "OPEC+ announced 2Mbpd cut from Nov 2022",
    ),
    HistoricalEvent(
        name         = "RBI Rate Hike 50bps (Jun 2022)",
        primary_node = "repo_rate",
        direction    = Sign.positive,
        event_date   = "2022-06-08",
        notes        = "Emergency 50bps hike; total 190bps in FY23",
    ),
    HistoricalEvent(
        name         = "India CPI 7.79% Surprise (Apr 2022)",
        primary_node = "inflation_cpi",
        direction    = Sign.positive,
        event_date   = "2022-05-12",
        notes        = "CPI well above 6% RBI upper band",
    ),
    HistoricalEvent(
        name         = "Russia-Ukraine War Outbreak (Feb 2022)",
        primary_node = "geopolitical_risk",
        direction    = Sign.positive,
        event_date   = "2022-02-24",
        notes        = "Russian invasion; oil spiked, FPIs fled EM",
    ),
    HistoricalEvent(
        name         = "RBI Rate Cut 40bps COVID (May 2020)",
        primary_node = "repo_rate",
        direction    = Sign.negative,
        event_date   = "2020-05-22",
        notes        = "Emergency cut during COVID lockdown",
    ),
    HistoricalEvent(
        name         = "OPEC Price War Crude Crash (Mar 2020)",
        primary_node = "crude_oil",
        direction    = Sign.negative,
        event_date   = "2020-03-09",
        notes        = "Saudi-Russia price war + COVID demand crash",
    ),
    HistoricalEvent(
        name         = "INR at 76+ USD/INR (Mar 2020)",
        primary_node = "inr",
        direction    = Sign.positive,
        event_date   = "2020-03-23",
        notes        = "Peak COVID panic; INR hit 76.50",
    ),
    HistoricalEvent(
        name         = "RBI Rate Hike 25bps (Feb 2023)",
        primary_node = "repo_rate",
        direction    = Sign.positive,
        event_date   = "2023-02-08",
        notes        = "Last hike of the current cycle (as of writing)",
    ),
    HistoricalEvent(
        name         = "US Fed Taper Tantrum Signal (May 2022)",
        primary_node = "us_fed_rate",
        direction    = Sign.positive,
        event_date   = "2022-05-04",
        notes        = "Fed raised 50bps; signalled aggressive path",
    ),
    HistoricalEvent(
        name         = "India CPI 6.83% Spike (Aug 2023)",
        primary_node = "inflation_cpi",
        direction    = Sign.positive,
        event_date   = "2023-09-12",
        notes        = "Above 6% band; tomato prices +300%",
    ),
]


def _make_event(he: HistoricalEvent) -> ExtractedEvent:
    return ExtractedEvent(
        event_type        = he.name,
        entities          = [he.primary_node],
        direction         = he.direction,
        magnitude         = None,
        region            = "India",
        evidence_sentence = he.notes,
        primary_node      = he.primary_node,
        unlinked_entities = [],
    )


@dataclass
class BacktestResult:
    event_name:  str
    event_date:  str
    asset:       str
    node_id:     str
    predicted:   str   # "+", "-", "?"
    car:         Optional[float]
    actual:      Optional[str]  # "+", "-", None
    match:       Optional[bool]


def run_backtest() -> list[BacktestResult]:
    results: list[BacktestResult] = []

    for he in HISTORICAL_EVENTS:
        print(f"\n>  {he.name} ({he.event_date})")
        event = _make_event(he)
        paths, assets = propagate(event)

        top5 = assets[:5]
        if not top5:
            print("   No assets predicted -- primary node may not connect to the graph.")
            continue

        for asset in top5:
            if asset.direction == Sign.ambiguous:
                print(f"   * {asset.label:<35} predicted: ?  (skip -- ambiguous)")
                results.append(BacktestResult(
                    event_name = he.name, event_date = he.event_date,
                    asset      = asset.label, node_id    = asset.node_id,
                    predicted  = "?",  car = None, actual = None, match = None,
                ))
                continue

            vr = run_event_study(asset.node_id, he.event_date, asset.direction)
            match_str = "[OK]" if vr.direction_match else ("[MISMATCH]" if vr.direction_match is False else "N/A")
            actual_dir = ("+" if vr.car and vr.car > 0 else
                          ("-" if vr.car and vr.car < 0 else None)) if vr.car is not None else None

            print(
                f"   * {asset.label:<35} predicted: {asset.direction.value}  "
                f"CAR: {vr.car:+.3%}  match: {match_str}"
                if vr.car is not None else
                f"   * {asset.label:<35} predicted: {asset.direction.value}  "
                f"[no market data]"
            )

            results.append(BacktestResult(
                event_name = he.name,  event_date = he.event_date,
                asset      = asset.label, node_id = asset.node_id,
                predicted  = asset.direction.value,
                car        = vr.car,
                actual     = actual_dir,
                match      = vr.direction_match,
            ))

    return results


def summarise(results: list[BacktestResult]) -> None:
    df = pd.DataFrame([r.__dict__ for r in results])

    # Only evaluate non-ambiguous predictions with market data
    evaluable = df[
        (df["predicted"] != "?") & (df["match"].notna())
    ]

    total      = len(evaluable)
    correct    = int(evaluable["match"].sum())
    hit_rate   = correct / total if total > 0 else float("nan")

    print("\n" + "=" * 60)
    print("BACKTEST SUMMARY")
    print("=" * 60)
    print(f"Events tested      : {len(HISTORICAL_EVENTS)}")
    print(f"Asset predictions  : {len(df)} total")
    print(f"Evaluable (non-?, with data): {total}")
    print(f"Direction correct  : {correct}")
    print(f"Hit rate           : {hit_rate:.1%}" if total > 0 else "Hit rate: N/A (insufficient data)")
    print()
    print("NOTE: Hit rate measures directional accuracy of the SEED GRAPH propagation")
    print("      using a market-model event study with Nifty 50 as benchmark.")
    print("      The benchmark itself is affected by macro events — treat with caution.")
    print("      Only numbers computed by this script are reported here.")
    print("=" * 60)

    # Save CSV
    out_path = Path(__file__).parent.parent / "data" / "backtest_results.csv"
    out_path.parent.mkdir(exist_ok=True)
    df.to_csv(out_path, index=False)
    print(f"\nFull results saved to: {out_path}")


if __name__ == "__main__":
    print("Market Impact Graph -- Historical Backtest")
    print("=" * 60)
    print("This will download market data from yfinance. May take 2-3 minutes.\n")
    results = run_backtest()
    summarise(results)
