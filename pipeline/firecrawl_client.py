"""Firecrawl search/scrape with disk cache and credit tracking."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Optional

import httpx

CACHE_DIR = Path(__file__).resolve().parent.parent / "cache"
CACHE_DIR.mkdir(exist_ok=True)

FIRECRAWL_BASE = "https://api.firecrawl.dev/v1"


class CreditTracker:
    """Track Firecrawl credits; abort projection over 450."""

    def __init__(self, limit: int = 450) -> None:
        self.limit = limit
        self.total = 0
        self.per_app: dict[str, int] = {}
        self._current_app = ""

    def set_app(self, app_name: str) -> None:
        self._current_app = app_name
        self.per_app.setdefault(app_name, 0)

    def add(self, credits: int, reason: str = "") -> None:
        self.total += credits
        if self._current_app:
            self.per_app[self._current_app] = self.per_app.get(self._current_app, 0) + credits
        print(f"[firecrawl] +{credits} credits ({reason}) running_total={self.total}/{self.limit}")

    def projected_ok(self, apps_done: int, apps_total: int, batch_remaining: int) -> bool:
        if apps_done == 0:
            return True
        avg = self.total / apps_done
        projected = self.total + avg * batch_remaining
        if projected > self.limit:
            print(
                f"[firecrawl] ABORT projected {projected:.0f} > {self.limit} "
                f"(done={apps_done}/{apps_total}, avg={avg:.1f})"
            )
            return False
        return True


class FirecrawlClient:
    def __init__(self, api_key: Optional[str] = None, tracker: Optional[CreditTracker] = None) -> None:
        self.api_key = api_key or os.getenv("FIRECRAWL_API_KEY", "")
        self.tracker = tracker or CreditTracker()
        self._client = httpx.Client(timeout=60.0)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _cache_path(self, url: str) -> Path:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return CACHE_DIR / f"{digest}.md"

    def scrape(self, url: str) -> tuple[Optional[str], Optional[str]]:
        """
        Returns (markdown, error_reason).
        Cache hit costs zero credits.
        """
        path = self._cache_path(url)
        meta_path = path.with_suffix(".json")
        if path.exists():
            text = path.read_text(encoding="utf-8")
            print(f"[firecrawl] cache hit {url}")
            return text, None

        if not self.api_key:
            return None, "FIRECRAWL_API_KEY missing"

        try:
            resp = self._client.post(
                f"{FIRECRAWL_BASE}/scrape",
                headers=self._headers(),
                json={"url": url, "formats": ["markdown"]},
            )
            if resp.status_code == 403:
                return None, "403 forbidden"
            if resp.status_code != 200:
                return None, f"http {resp.status_code}: {resp.text[:200]}"
            data = resp.json()
            md = (
                (data.get("data") or {}).get("markdown")
                or data.get("markdown")
                or ""
            )
            if not md.strip():
                return None, "empty response"
            path.write_text(md, encoding="utf-8")
            meta_path.write_text(json.dumps({"url": url}, indent=2), encoding="utf-8")
            # Firecrawl scrape typically 1 credit
            self.tracker.add(1, f"scrape {url}")
            return md, None
        except httpx.TimeoutException:
            return None, "timeout"
        except Exception as e:
            return None, str(e)

    def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """Return list of {url, title, description}. Cached by query hash."""
        digest = hashlib.sha256(f"search:{query}:{limit}".encode()).hexdigest()
        cache_path = CACHE_DIR / f"search_{digest}.json"
        if cache_path.exists():
            print(f"[firecrawl] search cache hit q={query!r}")
            return json.loads(cache_path.read_text(encoding="utf-8"))

        if not self.api_key:
            return []

        try:
            resp = self._client.post(
                f"{FIRECRAWL_BASE}/search",
                headers=self._headers(),
                json={"query": query, "limit": limit},
            )
            if resp.status_code != 200:
                print(f"[firecrawl] search failed {resp.status_code}")
                return []
            data = resp.json()
            results = data.get("data") or data.get("web") or []
            # normalize
            out = []
            for r in results:
                if isinstance(r, dict):
                    out.append(
                        {
                            "url": r.get("url") or r.get("link") or "",
                            "title": r.get("title") or "",
                            "description": r.get("description") or r.get("snippet") or "",
                        }
                    )
            cache_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
            self.tracker.add(1, f"search {query!r}")
            return out
        except Exception as e:
            print(f"[firecrawl] search error: {e}")
            return []
