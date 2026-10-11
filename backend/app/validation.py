"""
validation.py — yfinance event study for market-data support.  STEP 6.

Method: Standard market model event study.
  1. Estimation window: T−91 to T−11 days (80 trading days before the event).
  2. Fit OLS: asset_return = α + β × market_return + ε  (market = Nifty 50).
  3. Event window: T−2 to T+3 days (5-day window around event).
  4. Abnormal return: AR_t = actual_return_t − (α + β × market_return_t)
  5. CAR = sum of AR over event window.
  6. Direction match: CAR > 0 → "+", CAR < 0 → "−".

Limitations documented in every result (per spec):
  • Macro events move the entire market — the benchmark regression is noisy.
  • The benchmark (Nifty 50) is itself affected by the same event.
  • Results are INDICATIVE only; treat as weak qualitative signal.

Fails gracefully: if yfinance download fails, returns ValidationResult with car=None.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from app.schemas import Sign, ValidationResult

logger = logging.getLogger(__name__)

TICKER_MAP_PATH    = Path(__file__).parent / "ticker_map.json"
ESTIMATION_DAYS    = 80     # pre-event estimation window length
PRE_EVENT_OFFSET   = 10     # start estimation this many days before event
EVENT_WINDOW_PRE   = 2      # days before event to include in CAR
EVENT_WINDOW_POST  = 3      # days after event to include in CAR

_CAVEAT = (
    "Indicative only. Macro events affect the entire market simultaneously; "
    "the Nifty 50 benchmark is itself impacted, making the abnormal return "
    "estimate noisy. Do not treat direction match as causal confirmation."
)


def _load_ticker_map() -> dict[str, str]:
    raw = json.loads(TICKER_MAP_PATH.read_text())
    return raw.get("node_ticker_map", {})


def _download(ticker: str, start: str, end: str) -> Optional[pd.Series]:
    """Download adjusted close prices from yfinance.  Returns None on failure."""
    try:
        import yfinance as yf
        data = yf.download(
            ticker,
            start=start,
            end=end,
            auto_adjust=True,
            progress=False,
        )
        if data.empty:
            return None
        close = data["Close"]
        if hasattr(close, "squeeze"):
            close = close.squeeze()
        return close
    except Exception as exc:
        logger.warning("yfinance download failed for %s: %s", ticker, exc)
        return None


def _date_offset(date_str: str, offset_days: int) -> str:
    """Return ISO date string for date_str ± offset_days calendar days."""
    dt = pd.Timestamp(date_str)
    return (dt + pd.Timedelta(days=offset_days)).strftime("%Y-%m-%d")


def run_event_study(
    node_id:      str,
    event_date:   str,
    predicted_dir: Sign,
) -> ValidationResult:
    """
    Run market-model event study for a single asset.

    Args:
        node_id:       Seed graph node id (looked up in ticker_map).
        event_date:    ISO date string (YYYY-MM-DD).
        predicted_dir: Predicted direction from causal propagation.

    Returns:
        ValidationResult with CAR and direction_match (or car=None on failure).
    """
    ticker_map = _load_ticker_map()
    ticker     = ticker_map.get(node_id)
    benchmark  = "^NSEI"  # Nifty 50 as market benchmark

    no_data_result = ValidationResult(
        ticker          = ticker or "N/A",
        node_id         = node_id,
        car             = None,
        event_date      = event_date,
        window_days     = EVENT_WINDOW_PRE + EVENT_WINDOW_POST + 1,
        direction_match = None,
        label           = "indicative",
        note            = _CAVEAT,
    )

    if not ticker:
        no_data_result.note = f"No ticker mapped for node '{node_id}'. " + _CAVEAT
        return no_data_result

    # ── Date ranges ────────────────────────────────────────────────────────────
    est_start = _date_offset(event_date, -(ESTIMATION_DAYS + PRE_EVENT_OFFSET + 5))
    est_end   = _date_offset(event_date, -(PRE_EVENT_OFFSET))
    evt_start = _date_offset(event_date, -(EVENT_WINDOW_PRE + 2))
    evt_end   = _date_offset(event_date, EVENT_WINDOW_POST + 2)

    # ── Download data ──────────────────────────────────────────────────────────
    asset_est   = _download(ticker,    est_start, est_end)
    mkt_est     = _download(benchmark, est_start, est_end)
    asset_evt   = _download(ticker,    evt_start, evt_end)
    mkt_evt     = _download(benchmark, evt_start, evt_end)

    if any(x is None for x in [asset_est, mkt_est, asset_evt, mkt_evt]):
        logger.warning("Market data download failed for %s (%s)", ticker, node_id)
        return no_data_result

    # ── Returns ────────────────────────────────────────────────────────────────
    asset_ret_est = asset_est.pct_change().dropna()
    mkt_ret_est   = mkt_est.pct_change().dropna()
    asset_ret_evt = asset_evt.pct_change().dropna()
    mkt_ret_evt   = mkt_evt.pct_change().dropna()

    # Align on common dates
    est_df = pd.concat([asset_ret_est, mkt_ret_est], axis=1).dropna()
    est_df.columns = ["asset", "market"]
    if len(est_df) < 20:
        no_data_result.note = f"Insufficient estimation window data for {ticker}. " + _CAVEAT
        return no_data_result

    evt_df = pd.concat([asset_ret_evt, mkt_ret_evt], axis=1).dropna()
    evt_df.columns = ["asset", "market"]
    if evt_df.empty:
        no_data_result.note = f"No event window data for {ticker}. " + _CAVEAT
        return no_data_result

    # ── OLS market model ───────────────────────────────────────────────────────
    X = np.column_stack([np.ones(len(est_df)), est_df["market"].values])
    y = est_df["asset"].values
    try:
        coeffs, _, _, _ = np.linalg.lstsq(X, y, rcond=None)
    except np.linalg.LinAlgError:
        return no_data_result

    alpha, beta = coeffs[0], coeffs[1]

    # ── Abnormal returns and CAR ───────────────────────────────────────────────
    expected_ret = alpha + beta * evt_df["market"].values
    ar           = evt_df["asset"].values - expected_ret
    car          = float(ar.sum())

    # ── Direction match ────────────────────────────────────────────────────────
    if predicted_dir == Sign.ambiguous:
        direction_match = None
    else:
        car_positive = car > 0
        pred_positive = predicted_dir == Sign.positive
        direction_match = car_positive == pred_positive

    return ValidationResult(
        ticker          = ticker,
        node_id         = node_id,
        car             = round(car, 5),
        event_date      = event_date,
        window_days     = len(evt_df),
        direction_match = direction_match,
        label           = "indicative",
        note            = _CAVEAT,
    )


def run_validation_for_assets(
    affected_assets,   # list[AffectedAsset]
    event_date: Optional[str],
) -> tuple[list[ValidationResult], dict[str, float]]:
    """
    Run event study for all affected assets that have mapped tickers.

    Returns:
        validation_results : list of ValidationResult
        market_support_map : node_id → float ∈ [0,1]  (for confidence.py)
    """
    if not event_date:
        return [], {}

    ticker_map         = _load_ticker_map()
    validation_results = []
    market_support_map: dict[str, float] = {}

    for asset in affected_assets:
        if asset.node_id not in ticker_map:
            continue
        result = run_event_study(asset.node_id, event_date, asset.direction)
        validation_results.append(result)

        if result.car is not None and result.direction_match is not None:
            market_support_map[asset.node_id] = 1.0 if result.direction_match else 0.0

    return validation_results, market_support_map
