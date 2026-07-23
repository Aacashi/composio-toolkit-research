"""HTTP liveness checks before Tavily extract / accepting Call 1 URLs."""

from __future__ import annotations

from typing import Optional

import httpx

# In-process cache for one pipeline process.
_LIVE_CACHE: dict[str, bool] = {}

TIMEOUT = 8.0
HEADERS = {
    "User-Agent": "composio-toolkit-research/1.0 (+liveness-check)",
    "Accept": "*/*",
}


def url_is_live(url: str, *, client: Optional[httpx.Client] = None) -> bool:
    """
    Return True if URL looks reachable (2xx/3xx).
    HEAD first; on method-not-allowed / forbidden, fall back to short GET.
    """
    raw = (url or "").strip()
    if not raw.startswith(("http://", "https://")):
        return False
    if raw in _LIVE_CACHE:
        return _LIVE_CACHE[raw]

    own = client is None
    http = client or httpx.Client(follow_redirects=True, timeout=TIMEOUT, headers=HEADERS)
    live = False
    try:
        try:
            r = http.head(raw)
            if r.status_code in (405, 403, 400):
                r = http.get(raw, headers={**HEADERS, "Range": "bytes=0-0"})
            live = 200 <= r.status_code < 400
        except Exception:
            try:
                r = http.get(raw, headers={**HEADERS, "Range": "bytes=0-0"})
                live = 200 <= r.status_code < 400
            except Exception:
                live = False
    finally:
        if own:
            http.close()

    _LIVE_CACHE[raw] = live
    return live


def clear_live_cache() -> None:
    _LIVE_CACHE.clear()
