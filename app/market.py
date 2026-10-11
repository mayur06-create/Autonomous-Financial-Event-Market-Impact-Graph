"""Market data and event-study engine for NewsGraph.
Calculates real 'before vs after the news' price reactions, market-model abnormal returns (AR/CAR),
z-scores, volume spikes, and empirical validation verdicts.
"""
import concurrent.futures
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import sqlite3
import threading
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from . import config

TICKERS_FILE = config.BASE_DIR / "data" / "tickers.json"
_TICKERS_MAP: Optional[Dict[str, dict]] = None
_TICKERS_LOCK = threading.Lock()


def get_tickers_map() -> Dict[str, dict]:
    global _TICKERS_MAP
    with _TICKERS_LOCK:
        if _TICKERS_MAP is None:
            if TICKERS_FILE.exists():
                try:
                    _TICKERS_MAP = json.loads(TICKERS_FILE.read_text(encoding="utf-8"))
                except Exception:
                    _TICKERS_MAP = {}
            else:
                _TICKERS_MAP = {}
        return _TICKERS_MAP


def resolve_ticker(name_or_node: str) -> dict:
    """Resolve a KG node, company, or sector name to ticker info."""
    tmap = get_tickers_map()
    if not name_or_node:
        return {"ticker": None, "status": "no_data", "reason": "Empty asset name"}

    # Exact match
    if name_or_node in tmap:
        res = dict(tmap[name_or_node])
        res["name"] = name_or_node
        return res

    # Case-insensitive match
    lower_map = {k.lower(): v for k, v in tmap.items()}
    if name_or_node.lower() in lower_map:
        res = dict(lower_map[name_or_node.lower()])
        res["name"] = name_or_node
        return res

    # Cleaned name or suffix checks
    clean = name_or_node.replace(".NS", "").replace("^", "").strip()
    if clean.lower() in lower_map:
        res = dict(lower_map[clean.lower()])
        res["name"] = name_or_node
        return res

    # If it ends with .NS or starts with ^, treat as direct Yahoo ticker
    if name_or_node.endswith(".NS") or name_or_node.startswith("^") or "=" in name_or_node:
        return {
            "name": name_or_node,
            "ticker": name_or_node,
            "type": "Asset",
            "benchmark": "^NSEI" if name_or_node.endswith(".NS") else None,
            "is_proxy": false,
            "status": "ok"
        }

    return {
        "name": name_or_node,
        "ticker": None,
        "status": "no_data",
        "reason": f"No ticker mapping found for '{name_or_node}'"
    }


# ------------------------------------------------------------------ SQLite Price Cache
def _init_price_cache_db():
    p = config.db_path()
    os.makedirs(p.parent, exist_ok=True)
    conn = sqlite3.connect(str(p), timeout=10.0)
    with conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS price_cache(
            ticker TEXT,
            interval TEXT,
            start TEXT,
            end TEXT,
            json TEXT,
            fetched_at TEXT,
            PRIMARY KEY(ticker, interval, start, end)
        )
        """)
    conn.close()


_init_price_cache_db()


def _get_cached_price(ticker: str, interval: str, start: str, end: str) -> Optional[dict]:
    try:
        conn = sqlite3.connect(str(config.db_path()), timeout=5.0)
        conn.row_factory = sqlite3.Row
        with conn:
            cur = conn.execute(
                "SELECT json FROM price_cache WHERE ticker=? AND interval=? AND start=? AND end=?",
                (ticker, interval, start, end)
            )
            row = cur.fetchone()
        conn.close()
        if row:
            return json.loads(row["json"])
    except Exception:
        pass
    return None


def _set_cached_price(ticker: str, interval: str, start: str, end: str, data: dict):
    try:
        conn = sqlite3.connect(str(config.db_path()), timeout=5.0)
        now_iso = datetime.now(timezone.utc).isoformat()
        with conn:
            conn.execute(
                """INSERT OR REPLACE INTO price_cache(ticker, interval, start, end, json, fetched_at)
                   VALUES(?, ?, ?, ?, ?, ?)""",
                (ticker, interval, start, end, json.dumps(data), now_iso)
            )
        conn.close()
    except Exception:
        pass


# ------------------------------------------------------------------ Event Time Alignment
def parse_utc_to_ist(iso_or_date_str: str) -> datetime:
    """Parse UTC timestamp string into an aware or naive IST datetime."""
    s = (iso_or_date_str or "").strip()
    if not s:
        return datetime.now(timezone(timedelta(hours=5, minutes=30)))

    # If only YYYY-MM-DD
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        # Default to 09:30:00 IST on that day
        dt = datetime.strptime(s, "%Y-%m-%d")
        return dt.replace(hour=9, minute=30, tzinfo=timezone(timedelta(hours=5, minutes=30)))

    # Handle Z and ISO formats
    s_clean = s.replace("Z", "+00:00")
    try:
        dt_utc = datetime.fromisoformat(s_clean)
        if dt_utc.tzinfo is None:
            dt_utc = dt_utc.replace(tzinfo=timezone.utc)
        ist_tz = timezone(timedelta(hours=5, minutes=30))
        return dt_utc.astimezone(ist_tz)
    except Exception:
        dt = datetime.strptime(s[:10], "%Y-%m-%d")
        return dt.replace(hour=9, minute=30, tzinfo=timezone(timedelta(hours=5, minutes=30)))


def align_event_trading_session(dt_ist: datetime) -> Tuple[datetime, str, bool]:
    """Align event time to NSE trading session.
    Market hours: 09:15 - 15:30 IST, Monday (0) to Friday (4).
    Returns (reaction_start_date, reason, is_intraday_bar).
    """
    weekday = dt_ist.weekday()  # 0=Mon, 4=Fri, 5=Sat, 6=Sun
    time_min = dt_ist.hour * 60 + dt_ist.minute
    market_open = 9 * 60 + 15
    market_close = 15 * 60 + 30

    # Weekend
    if weekday == 5:  # Saturday
        next_mon = (dt_ist + timedelta(days=2)).replace(hour=9, minute=15, second=0, microsecond=0)
        return next_mon, "Published on weekend (Saturday); reaction starts Monday open", False
    if weekday == 6:  # Sunday
        next_mon = (dt_ist + timedelta(days=1)).replace(hour=9, minute=15, second=0, microsecond=0)
        return next_mon, "Published on weekend (Sunday); reaction starts Monday open", False

    # Weekday before open
    if time_min < market_open:
        start_dt = dt_ist.replace(hour=9, minute=15, second=0, microsecond=0)
        return start_dt, "Published before NSE open (09:15 IST); reaction starts at open", False

    # Weekday inside market hours
    if market_open <= time_min <= market_close:
        return dt_ist, "Published during NSE trading hours (09:15 - 15:30 IST); reaction starts immediately", True

    # Weekday after close
    days_to_add = 3 if weekday == 4 else 1  # Friday after close -> Monday
    next_session = (dt_ist + timedelta(days=days_to_add)).replace(hour=9, minute=15, second=0, microsecond=0)
    return next_session, "Published after NSE close (15:30 IST); reaction starts next trading session", False


# ------------------------------------------------------------------ Yahoo Finance Fetcher
def fetch_history(ticker: str, start_date: str, end_date: str, interval: str = "1d", timeout: float = 8.0) -> List[dict]:
    """Fetch OHLCV data using yfinance with timeout and SQLite caching."""
    if not ticker:
        return []

    # Check cache first
    cached = _get_cached_price(ticker, interval, start_date, end_date)
    if cached is not None:
        return cached

    def _call_yf():
        import yfinance as yf
        t = yf.Ticker(ticker)
        # Add 1 day buffer to end_date for yfinance
        df = t.history(start=start_date, end=end_date, interval=interval, auto_adjust=True)
        if df is None or df.empty:
            return []
        bars = []
        for idx, row in df.iterrows():
            d_str = idx.strftime("%Y-%m-%d")
            ts_str = idx.isoformat()
            bars.append({
                "date": d_str,
                "ts": ts_str,
                "open": float(row.get("Open", 0.0)),
                "high": float(row.get("High", 0.0)),
                "low": float(row.get("Low", 0.0)),
                "close": float(row.get("Close", 0.0)),
                "volume": float(row.get("Volume", 0.0)),
            })
        return bars

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(_call_yf)
        try:
            bars = fut.result(timeout=timeout)
        except Exception:
            bars = []

    if bars:
        _set_cached_price(ticker, interval, start_date, end_date, bars)

    return bars


# ------------------------------------------------------------------ Event Study Analytics
def compute_event_study(
    asset_name: str,
    event_dt_ist: datetime,
    expected_sign: int = 1,
    pre_window: int = 30,
    post_window: int = 10,
    interval: str = "1d",
    other_event_dates: Optional[List[str]] = None,
) -> dict:
    """Run full event study on an asset for an event published at event_dt_ist.
    Rejects future event dates.
    Calculates T0 pre-news close, normalized 100 series, market model AR/CAR/z, volume ratio,
    verdict, and confounded warning.
    """
    now_ist = datetime.now(timezone(timedelta(hours=5, minutes=30)))
    if event_dt_ist > now_ist + timedelta(hours=1):
        raise ValueError(f"Event date cannot be in the future (event: {event_dt_ist.strftime('%Y-%m-%d')}, today: {now_ist.strftime('%Y-%m-%d')})")

    resolved = resolve_ticker(asset_name)
    ticker = resolved.get("ticker")
    if not ticker or resolved.get("status") == "no_data":
        return {
            "name": asset_name,
            "ticker": ticker,
            "status": "no_data",
            "reason": resolved.get("reason", "No traded ticker available for this indicator/node"),
            "is_proxy": resolved.get("is_proxy", False),
            "proxy_name": resolved.get("proxy_name"),
            "benchmark": resolved.get("benchmark"),
        }

    benchmark_ticker = resolved.get("benchmark") or ("^NSEI" if ticker.endswith(".NS") else None)
    is_raw_z = resolved.get("raw_z", False) or (benchmark_ticker is None)

    rx_session, session_reason, is_intraday = align_event_trading_session(event_dt_ist)
    rx_date_str = rx_session.strftime("%Y-%m-%d")

    # We need enough history for:
    # 1. Estimation window: 120 sessions ending 6 sessions before T0
    # 2. Event window: [-pre_window, +post_window]
    # In calendar days, ~250 trading days is ~380 calendar days back.
    cal_start = (event_dt_ist - timedelta(days=360)).strftime("%Y-%m-%d")
    cal_end = (event_dt_ist + timedelta(days=60)).strftime("%Y-%m-%d")

    asset_bars = fetch_history(ticker, cal_start, cal_end, interval="1d", timeout=8.0)
    if not asset_bars:
        return {
            "name": asset_name,
            "ticker": ticker,
            "status": "unavailable",
            "reason": f"No market history returned by Yahoo Finance for {ticker}",
            "is_proxy": resolved.get("is_proxy", False),
            "proxy_name": resolved.get("proxy_name"),
        }

    # Find T0 bar index: last trading close BEFORE the reaction date
    # A bar with date < rx_date_str
    bar_dates = [b["date"] for b in asset_bars]
    t0_idx = None
    for i in range(len(bar_dates) - 1, -1, -1):
        if bar_dates[i] < rx_date_str:
            t0_idx = i
            break

    if t0_idx is None or t0_idx < 15:
        # Fallback if news was on the first day of history
        t0_idx = max(0, min(len(asset_bars) - 1, 10))

    t0_bar = asset_bars[t0_idx]
    t0_date = t0_bar["date"]
    pre_close = t0_bar["close"]
    if pre_close <= 0.0:
        pre_close = 1.0

    # Pre-news volatility (20d): std dev of daily returns over 20 sessions ending at T0
    vol_start_idx = max(0, t0_idx - 20)
    pre_closes = [b["close"] for b in asset_bars[vol_start_idx : t0_idx + 1]]
    if len(pre_closes) >= 3:
        rets_20d = [
            (pre_closes[j] - pre_closes[j - 1]) / pre_closes[j - 1]
            for j in range(1, len(pre_closes))
            if pre_closes[j - 1] > 0
        ]
        pre_vol_20d = max(0.005, float(np.std(rets_20d))) if rets_20d else 0.015
    else:
        pre_vol_20d = 0.015

    # 20d Average volume ending at T0
    pre_vols = [b["volume"] for b in asset_bars[vol_start_idx : t0_idx + 1] if b["volume"] > 0]
    avg_vol_20d = float(np.mean(pre_vols)) if pre_vols else 1.0

    # Slicing the event window: [-pre_window, +post_window] around T0
    w_start_idx = max(0, t0_idx - pre_window)
    w_end_idx = min(len(asset_bars) - 1, t0_idx + post_window)
    event_bars = asset_bars[w_start_idx : w_end_idx + 1]

    sessions_after = (w_end_idx - t0_idx)
    window_complete = sessions_after >= post_window

    # Market Model Fit (Alpha / Beta) against Benchmark
    alpha, beta, resid_sigma = 0.0, 1.0, pre_vol_20d
    bm_bars_map = {}
    if benchmark_ticker and not is_raw_z:
        bm_bars = fetch_history(benchmark_ticker, cal_start, cal_end, interval="1d", timeout=8.0)
        bm_bars_map = {b["date"]: b["close"] for b in bm_bars}

        # Estimation window: 120 sessions ending 6 sessions before T0
        est_end = max(0, t0_idx - 6)
        est_start = max(0, est_end - 120)
        asset_est = asset_bars[est_start : est_end + 1]

        y_rets, x_rets = [], []
        for k in range(1, len(asset_est)):
            d_curr = asset_est[k]["date"]
            d_prev = asset_est[k - 1]["date"]
            c_curr = asset_est[k]["close"]
            c_prev = asset_est[k - 1]["close"]
            if c_prev > 0 and d_curr in bm_bars_map and d_prev in bm_bars_map:
                bm_prev = bm_bars_map[d_prev]
                bm_curr = bm_bars_map[d_curr]
                if bm_prev > 0:
                    y_rets.append((c_curr - c_prev) / c_prev)
                    x_rets.append((bm_curr - bm_prev) / bm_prev)

        if len(y_rets) >= 20:
            x_arr = np.array(x_rets)
            y_arr = np.array(y_rets)
            var_x = float(np.var(x_arr))
            if var_x > 1e-7:
                beta = float(np.cov(y_arr, x_arr)[0, 1] / var_x)
                alpha = float(np.mean(y_arr) - beta * np.mean(x_arr))
                resids = y_arr - (alpha + beta * x_arr)
                resid_sigma = max(0.005, float(np.std(resids)))

    # Compute series data with normalisation, AR and CAR
    series = []
    cum_car = 0.0
    for idx_offset, b in enumerate(event_bars):
        c = b["close"]
        norm = round((c / pre_close) * 100.0, 2)
        actual_idx = w_start_idx + idx_offset

        # Daily raw return
        if actual_idx > 0:
            prev_c = asset_bars[actual_idx - 1]["close"]
            ret = (c - prev_c) / prev_c if prev_c > 0 else 0.0
        else:
            ret = 0.0

        # Abnormal return & CAR (accumulate starting at reaction day t0_idx + 1)
        ar = 0.0
        if actual_idx > t0_idx:
            if is_raw_z or not benchmark_ticker:
                ar = ret
            else:
                prev_d = asset_bars[actual_idx - 1]["date"]
                curr_d = b["date"]
                if prev_d in bm_bars_map and curr_d in bm_bars_map and bm_bars_map[prev_d] > 0:
                    bm_ret = (bm_bars_map[curr_d] - bm_bars_map[prev_d]) / bm_bars_map[prev_d]
                    expected_ret = alpha + beta * bm_ret
                    ar = ret - expected_ret
                else:
                    ar = ret
            cum_car += ar

        series.append({
            "ts": b["ts"],
            "date": b["date"],
            "close": round(c, 2),
            "norm_to_100_at_T0": norm,
            "ret": round(ret, 4),
            "abnormal_ret": round(ar, 4) if actual_idx > t0_idx else 0.0,
            "car": round(cum_car, 4) if actual_idx > t0_idx else 0.0,
            "is_reaction_session": actual_idx > t0_idx,
        })

    # Forward returns (+1d, +3d, +5d) from T0
    def _forward_ret(offset: int) -> Optional[float]:
        tgt_idx = t0_idx + offset
        if tgt_idx < len(asset_bars):
            c_tgt = asset_bars[tgt_idx]["close"]
            return round((c_tgt - pre_close) / pre_close * 100.0, 2)
        return None

    ret_1d = _forward_ret(1)
    ret_3d = _forward_ret(3)
    ret_5d = _forward_ret(5)

    # Reaction day volume ratio
    rx_vol = asset_bars[t0_idx + 1]["volume"] if t0_idx + 1 < len(asset_bars) else 0.0
    volume_ratio = round(rx_vol / avg_vol_20d, 2) if avg_vol_20d > 0 else 1.0

    # CAR and Z-scores over [0, +1], [0, +3], [0, +5]
    def _compute_car_and_z(n_days: int) -> Tuple[float, float]:
        if n_days <= 0 or sessions_after <= 0:
            return 0.0, 0.0
        n = min(n_days, sessions_after)
        sub_ars = [s["abnormal_ret"] for s in series if s["is_reaction_session"]][:n]
        tot_car = float(sum(sub_ars))
        sigma = resid_sigma if not is_raw_z else pre_vol_20d
        denom = sigma * math.sqrt(max(1, n))
        z = (tot_car / denom) if denom > 1e-7 else 0.0
        return round(tot_car * 100.0, 2), round(z, 2)

    car_1d, z_1d = _compute_car_and_z(1)
    car_3d, z_3d = _compute_car_and_z(3)
    car_5d, z_5d = _compute_car_and_z(5)

    # Primary event study z and CAR: choose 3d if available, else 1d
    primary_car = car_3d if sessions_after >= 3 else (car_1d if sessions_after >= 1 else 0.0)
    primary_z = z_3d if sessions_after >= 3 else (z_1d if sessions_after >= 1 else 0.0)

    # Verdict classification
    # confirmed: sign matches model's predicted sign and |z| >= 1.5
    # contradicted: opposite sign and |z| >= 1.5
    # inconclusive: otherwise
    verdict = "inconclusive"
    if sessions_after >= 1:
        observed_sign = 1 if primary_z > 0 else (-1 if primary_z < 0 else 0)
        if abs(primary_z) >= 1.5:
            if observed_sign == expected_sign:
                verdict = "confirmed"
            else:
                verdict = "contradicted"
        else:
            verdict = "inconclusive"

    # Confounded check: any other article hitting same asset within +-3 sessions
    confounded = False
    if other_event_dates:
        t0_d = datetime.strptime(t0_date, "%Y-%m-%d")
        for od in other_event_dates:
            try:
                od_dt = datetime.strptime(od[:10], "%Y-%m-%d")
                day_diff = abs((od_dt - t0_d).days)
                if 0 < day_diff <= 5:  # ~3 trading sessions is ~3-5 calendar days
                    confounded = True
                    break
            except Exception:
                pass

    return {
        "name": asset_name,
        "ticker": ticker,
        "status": "ok",
        "is_proxy": resolved.get("is_proxy", False),
        "proxy_name": resolved.get("proxy_name"),
        "benchmark": benchmark_ticker,
        "event_time_ist": event_dt_ist.strftime("%Y-%m-%d %H:%M:%S IST"),
        "session_alignment": {
            "reaction_date": rx_date_str,
            "reason": session_reason,
            "is_intraday": is_intraday,
            "t0_date": t0_date,
        },
        "pre_close": round(pre_close, 2),
        "pre_vol_20d_pct": round(pre_vol_20d * 100.0, 2),
        "volume_ratio": volume_ratio,
        "window_complete": window_complete,
        "sessions_after": sessions_after,
        "expected_sign": expected_sign,
        "returns": {
            "+1d": ret_1d,
            "+3d": ret_3d,
            "+5d": ret_5d,
        },
        "car": {
            "+1d": car_1d,
            "+3d": car_3d,
            "+5d": car_5d,
        },
        "z_score": {
            "+1d": z_1d,
            "+3d": z_3d,
            "+5d": z_5d,
            "primary": primary_z,
        },
        "market_model": {
            "alpha": round(alpha, 4),
            "beta": round(beta, 3),
            "resid_sigma": round(resid_sigma, 4),
            "model_type": "raw_vol" if is_raw_z else "market_model",
        },
        "verdict": verdict,
        "confounded": confounded,
        "series": series,
    }


# ------------------------------------------------------------------ Multi-Asset Batch Runner
def run_article_reaction_study(
    kb,
    article_id: str,
    asset_names: Optional[List[str]] = None,
    pre_window: int = 30,
    post_window: int = 10,
) -> dict:
    """Run market reaction study for all key assets or specified assets for an article."""
    art = kb.article(article_id)
    if not art:
        # Check inbox
        inbox_it = kb.inbox_get(article_id)
        if inbox_it:
            raise ValueError("Article in inbox has not been analyzed yet. Run POST /api/news/analyze first.")
        raise ValueError(f"Article '{article_id}' not found")

    pub_at = art.get("published_at")
    dt_ist = parse_utc_to_ist(pub_at)

    # Determine default assets if none provided
    try:
        feats = json.loads(art.get("features_json") or "{}")
    except Exception:
        feats = {}

    # Extract other article dates in KB for confounding check
    all_arts = kb._all("SELECT published_at FROM articles WHERE id != ?", (article_id,))
    other_dates = [r["published_at"] for r in all_arts if r.get("published_at")]

    # If assets not specified, pick top affected assets by propagation / LLM impact
    targets = []
    if asset_names:
        for a in asset_names:
            targets.append((a.strip(), 1))
    else:
        # 1. Trigger node if traded
        trig = (feats.get("primary_event_meta") or {}).get("trigger_node")
        trig_sign = (feats.get("primary_event_meta") or {}).get("sign", 1)
        if trig:
            targets.append((trig, trig_sign))

        # 2. Linked entities in article
        for e in feats.get("entities", []):
            name = e.get("linked_node_id") or e.get("name")
            sign = 1 if (e.get("sentiment") or 0.0) >= 0 else -1
            if name and name not in [t[0] for t in targets]:
                targets.append((name, sign))

        # 3. Top sector proxies
        for s in kb._all("SELECT sector, score FROM sector_impacts WHERE article_id=? ORDER BY ABS(score) DESC LIMIT 3", (article_id,)):
            sec_name = s["sector"]
            sec_sign = 1 if s["score"] >= 0 else -1
            if sec_name not in [t[0] for t in targets]:
                targets.append((sec_name, sec_sign))

        # Always include benchmark ^NSEI if not already present
        if not any(t[0] in ("^NSEI", "Nifty 50") for t in targets):
            targets.append(("Nifty 50", 1))

    # Run in parallel with timeout safety
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        futures = {
            ex.submit(
                compute_event_study,
                asset_name=t[0],
                event_dt_ist=dt_ist,
                expected_sign=t[1],
                pre_window=pre_window,
                post_window=post_window,
                other_event_dates=other_dates,
            ): t for t in targets[:6]
        }
        for fut in concurrent.futures.as_completed(futures):
            t_info = futures[fut]
            try:
                res = fut.result()
                results.append(res)
            except Exception as ex_err:
                results.append({
                    "name": t_info[0],
                    "status": "unavailable",
                    "reason": str(ex_err),
                    "expected_sign": t_info[1]
                })

    # Sort results: benchmark first, then proxies/companies
    def _rank(r):
        if r.get("ticker") in ("^NSEI", "^GSPC"):
            return 0
        if r.get("status") == "ok":
            return 1
        return 2
    results.sort(key=_rank)

    # Scorecard for this article
    confirmed_n = sum(1 for r in results if r.get("verdict") == "confirmed")
    contradicted_n = sum(1 for r in results if r.get("verdict") == "contradicted")
    inconclusive_n = sum(1 for r in results if r.get("verdict") == "inconclusive")
    no_data_n = sum(1 for r in results if r.get("status") in ("no_data", "unavailable"))

    return {
        "article_id": article_id,
        "article_title": art.get("title", ""),
        "published_at_utc": pub_at,
        "published_at_ist": dt_ist.strftime("%Y-%m-%d %H:%M:%S IST"),
        "pre_window": pre_window,
        "post_window": post_window,
        "scorecard": {
            "confirmed": confirmed_n,
            "contradicted": contradicted_n,
            "inconclusive": inconclusive_n,
            "no_data": no_data_n,
            "total_tested": len(results),
        },
        "results": results,
    }


def compute_aggregate_scorecard(kb) -> dict:
    """Aggregate hit-rate across all analysed articles."""
    articles = kb._all("SELECT id, title, published_at FROM articles ORDER BY published_at DESC LIMIT 15")
    if not articles:
        return {
            "total_articles": 0,
            "total_predictions": 0,
            "confirmed": 0,
            "contradicted": 0,
            "inconclusive": 0,
            "hit_rate_pct": 0.0,
            "caveat": "No analysed articles available yet.",
        }

    total_conf, total_contra, total_inconc, total_preds = 0, 0, 0, 0
    article_summaries = []

    for art in articles:
        try:
            study = run_article_reaction_study(kb, art["id"])
            sc = study.get("scorecard", {})
            c = sc.get("confirmed", 0)
            ct = sc.get("contradicted", 0)
            inc = sc.get("inconclusive", 0)
            total_conf += c
            total_contra += ct
            total_inconc += inc
            total_preds += (c + ct + inc)
            article_summaries.append({
                "id": art["id"],
                "title": art["title"][:70],
                "confirmed": c,
                "contradicted": ct,
                "inconclusive": inc,
            })
        except Exception:
            continue

    tested_with_signal = total_conf + total_contra
    hit_rate = round(100.0 * total_conf / tested_with_signal, 1) if tested_with_signal > 0 else 0.0

    return {
        "total_articles": len(articles),
        "total_predictions": total_preds,
        "confirmed": total_conf,
        "contradicted": total_contra,
        "inconclusive": total_inconc,
        "tested_with_signal": tested_with_signal,
        "hit_rate_pct": hit_rate,
        "caveat": f"Based on {total_preds} predictions across {len(articles)} articles. Small sample size; not statistical or financial proof.",
        "articles": article_summaries,
    }
