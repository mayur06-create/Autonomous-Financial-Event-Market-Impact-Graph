"""Optional time-series validation using yfinance. Fails gracefully (returns None)."""
from functools import lru_cache

@lru_cache(maxsize=256)
def _returns(ticker):
    try:
        import yfinance as yf
        df = yf.download(ticker, period="2y", progress=False, auto_adjust=True)["Close"]
        if hasattr(df, "columns"): df = df.iloc[:, 0]
        return df.pct_change().dropna()
    except Exception:
        return None

def correlation(t1, t2):
    if not t1 or not t2: return None
    a, b = _returns(t1), _returns(t2)
    if a is None or b is None: return None
    j = a.to_frame("a").join(b.to_frame("b"), how="inner").dropna()
    if len(j) < 60: return None
    return round(float(j["a"].corr(j["b"])), 3)
