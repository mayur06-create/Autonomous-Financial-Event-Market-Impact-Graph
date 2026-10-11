"""Phase 1: live news from Marketaux (+ offline sample for testing without a key)."""
import hashlib
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

from . import config


class MarketauxError(RuntimeError):
    """Specific error for Marketaux API issues (401, 402, 429, etc.)."""
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


# In-memory tracking of Marketaux status and last known quota
_STATUS: Dict[str, Any] = {
    "state": None,       # ready | missing | invalid | quota_exhausted
    "remaining": None,   # integer remaining requests from last response
    "last_error": None,
}


def mask_key(k: str) -> str:
    """Mask key revealing only last 4 characters. Never exposes full key."""
    if not k:
        return ""
    if len(k) <= 4:
        return "••••"
    return ("•" * (len(k) - 4)) + k[-4:]


def get_marketaux_status() -> dict:
    """Return status of Marketaux integration.
    Performs a lightweight HEAD request with limit=0 when state is unknown to
    verify the key and fetch remaining quota without consuming API quota.
    """
    key = config.marketaux_key()
    if not key:
        return {
            "key_masked": "",
            "state": "missing",
            "remaining": None,
            "message": "Marketaux API key missing. Add MARKETAUX_API_KEY to .env",
            "configured": False,
        }

    # If we have no known state, attempt a HEAD request to verify key & quota.
    if _STATUS.get("state") is None:
        try:
            url = f"{config.MARKETAUX_URL}?api_token={urllib.parse.quote(key)}&limit=0"
            req = urllib.request.Request(url, method="HEAD")
            with urllib.request.urlopen(req, timeout=5) as r:
                # Update remaining quota from response headers if available.
                rem_hdr = (
                    r.headers.get("x-usagelimit-remaining")
                    or r.headers.get("x-ratelimit-remaining")
                    or r.headers.get("x-usagelimit-limit")
                )
                if rem_hdr:
                    try:
                        _STATUS["remaining"] = int(rem_hdr)
                    except Exception:
                        pass
                _STATUS["state"] = "ready"
                _STATUS["last_error"] = None
        except urllib.error.HTTPError as e:
            if e.code == 401:
                _STATUS["state"] = "invalid"
                _STATUS["last_error"] = "Invalid Marketaux API token (HTTP 401)."
            elif e.code == 402:
                _STATUS["state"] = "quota_exhausted"
                _STATUS["remaining"] = 0
                _STATUS["last_error"] = "Marketaux usage limit reached (HTTP 402)."
            elif e.code == 429:
                _STATUS["state"] = "rate_limited"
                _STATUS["remaining"] = 0
                _STATUS["last_error"] = "Marketaux rate limit exceeded (HTTP 429)."
            else:
                _STATUS["last_error"] = f"Marketaux HTTP {e.code}"
        except Exception:
            pass

    st = _STATUS.get("state")
    if not st:
        st = "ready"

    return {
        "key_masked": mask_key(key),
        "state": st,
        "remaining": _STATUS.get("remaining"),
        "message": _STATUS.get("last_error") or ("API key ready" if st == "ready" else st),
        "configured": True,
    }


def set_marketaux_status_for_test(state: str, remaining: Optional[int] = None, error: Optional[str] = None):
    """Helper for testing status states without HTTP calls."""
    _STATUS["state"] = state
    _STATUS["remaining"] = remaining
    _STATUS["last_error"] = error


@dataclass
class Article:
    uuid: str
    title: str
    description: str
    snippet: str
    url: str
    source: str
    published_at: str
    sentiment_score: Optional[float] = None
    entities: List[dict] = field(default_factory=list)

    @property
    def text(self) -> str:
        return ". ".join(p.strip() for p in (self.title, self.description, self.snippet) if p and p.strip())

    def to_dict(self) -> dict:
        return asdict(self)


def _parse(item: dict) -> Article:
    entities, scores = [], []
    for e in item.get("entities") or []:
        entities.append({k: e.get(k) for k in ("symbol", "name", "industry", "type", "country", "sentiment_score")})
        if e.get("sentiment_score") is not None:
            scores.append(e["sentiment_score"])
    url = item.get("url") or ""
    return Article(
        uuid=item.get("uuid") or hashlib.sha1(url.encode()).hexdigest()[:16],
        title=item.get("title") or "",
        description=item.get("description") or "",
        snippet=item.get("snippet") or "",
        url=url,
        source=item.get("source") or "",
        published_at=item.get("published_at") or "",
        sentiment_score=(sum(scores) / len(scores)) if scores else None,
        entities=entities,
    )


def parse_response(payload: dict) -> List[Article]:
    return [_parse(i) for i in payload.get("data", [])]


def fetch_news(search=None, symbols=None, industries=None, countries="in,us", language="en",
               limit=10, pages=1, published_after=None) -> List[Article]:
    key = config.marketaux_key()
    if not key:
        _STATUS["state"] = "missing"
        _STATUS["last_error"] = "MARKETAUX_API_KEY is not set (put it in .env or export it)."
        raise MarketauxError(401, "MARKETAUX_API_KEY is not set (put it in .env or export it).")

    out, seen = [], set()
    for page in range(1, pages + 1):
        params = {"api_token": key, "language": language, "limit": limit, "page": page,
                  "filter_entities": "true", "sort": "published_at"}
        for k, v in (("countries", countries), ("search", search), ("symbols", symbols),
                     ("industries", industries), ("published_after", published_after)):
            if v:
                params[k] = v
        req = urllib.request.Request(config.MARKETAUX_URL + "?" + urllib.parse.urlencode(params),
                                     headers={"User-Agent": "newsgraph/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                payload = json.load(r)

                # Read remaining quota from response headers or meta
                rem_hdr = (r.headers.get("x-usagelimit-remaining") or
                           r.headers.get("x-ratelimit-remaining") or
                           r.headers.get("x-usagelimit-limit"))
                if rem_hdr:
                    try:
                        _STATUS["remaining"] = int(rem_hdr)
                    except Exception:
                        pass

                meta = payload.get("meta") or {}
                if "remaining" in meta:
                    _STATUS["remaining"] = meta.get("remaining")
                elif "remaining_requests" in meta:
                    _STATUS["remaining"] = meta.get("remaining_requests")

                _STATUS["state"] = "ready"
                _STATUS["last_error"] = None
        except urllib.error.HTTPError as e:  # never echo the URL: it contains the token
            body_snippet = e.read().decode(errors="replace")[:300]
            if e.code == 401:
                _STATUS["state"] = "invalid"
                _STATUS["last_error"] = "Invalid Marketaux API token (HTTP 401). Please check your key in .env."
                raise MarketauxError(401, "Invalid Marketaux API token (HTTP 401). Check .env.") from None
            elif e.code == 402:
                _STATUS["state"] = "quota_exhausted"
                _STATUS["remaining"] = 0
                _STATUS["last_error"] = "Marketaux request quota exhausted (HTTP 402)."
                raise MarketauxError(402, "Marketaux usage limit reached (HTTP 402). Serving cached articles.") from None
            elif e.code == 429:
                _STATUS["state"] = "quota_exhausted"
                _STATUS["remaining"] = 0
                _STATUS["last_error"] = "Marketaux rate limit exceeded (HTTP 429)."
                raise MarketauxError(429, "Marketaux rate limit exceeded (HTTP 429). Serving cached articles.") from None
            else:
                _STATUS["last_error"] = f"Marketaux HTTP {e.code}: {body_snippet}"
                raise MarketauxError(e.code, f"Marketaux HTTP {e.code}: {body_snippet}") from None
        except urllib.error.URLError as e:
            _STATUS["last_error"] = f"Marketaux unreachable: {e.reason}"
            raise RuntimeError(f"Marketaux unreachable: {e.reason}") from None

        items = parse_response(payload)
        if not items:
            break
        for a in items:
            if a.uuid not in seen:
                seen.add(a.uuid)
                out.append(a)
    return out


def load_sample() -> List[Article]:
    path = config.BASE_DIR / "data" / "sample_news.json"
    return parse_response(json.loads(path.read_text(encoding="utf-8")))
